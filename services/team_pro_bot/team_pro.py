import asyncio
import logging
from services.base import BaseService, ServerUnavailable, BadAPIKey
from typing import Callable
from config import config
import aiohttp
import json
import datetime as dt
import team_pro_services, team_pro_countries


logger = logging.getLogger(__name__)


class TeamProService(BaseService):
    MAX_CACHING_TIME = 12  # in hours
    api_key = config['api_keys']['team_pro']
    _api_url = 'https://api.team-ye.net/stubs/handler_api.php'
    _handlers: dict[int, tuple[Callable, list, dict]] = {}

    def __init__(self):
        self._countries = team_pro_countries.countries
        self._services = team_pro_services.services
        self.aiohttp_session = aiohttp.ClientSession()


    async def get_balance(self) -> int:
        payload = {'action': 'getBalance', 'api_key': self.api_key}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            data = (await response.content.read()).decode()
            if data == 'BAD_KEY':
                raise BadAPIKey
            args = data.split(':')
            if args[0] == 'ACCESS_BALANCE':
                return float(args[1])
            else:
                raise ServerUnavailable("Server response not correct")

    async def get_countries(self) -> dict[str, str]:
        return self._countries

    async def get_services(self) -> dict[str, str]:
        return self._services


    async def get_price(self, country_id: str, service_id: str) -> int:
        if not (country_id in (await self.get_countries()).values() and service_id in (
                await self.get_services()).values()):
            raise ValueError('Unsupported country_id or value_id')
        payload = {"action": 'getPrices', "api_key": self.api_key, "country": country_id, "service": service_id}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            if response.status != 200:
                raise ServerUnavailable(f"Request failed with status code {response.status}")
            data = await response.json()

            first_cost = list(data.values())[0]['cost']
            cost_int = int(first_cost)

            return cost_int


    async def rent_number(self, country_id: str, service_id: str, handler: Callable[[str, str], None], *args,
                          **kwargs) -> str:
        if not (country_id in (await self.get_countries()).values() and service_id in (
                await self.get_services()).values()):
            raise ValueError('Unsupported country_id or value_id')
        payload = {'action': 'getNumber', 'api_key': self.api_key, 'service': service_id, 'country': country_id}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            response_text = await response.text()
            if not response_text:
                raise ServerUnavailable("Empty response from server")
            parts = response_text.split(':')
            if len(parts) != 3 or parts[0] != 'ACCESS_NUMBER':
                raise ServerUnavailable("Invalid response format")

            activation_id = parts[1]
            phone_number = parts[2]
        self._handlers[activation_id] = (handler, args, kwargs)
        return phone_number

    async def connect(self):
        self.aiohttp_session = aiohttp.ClientSession()
        self.polling_task = asyncio.create_task(self.polling())

    async def close(self):
        self.polling_task.cancel()
        await self.aiohttp_session.close()


    async def _check_sms(self, request_id) -> None:
        payload = {'action': 'getStatus', 'api_key': self.api_key, 'id': request_id}
        async with self.aiohttp_session.get(url=self._api_url, params=payload) as response:
            response_text = await response.text()
            if not response_text:
                raise ServerUnavailable("Empty response from server")
            if response_text == 'STATUS_WAIT_CODE':
                return
            if response_text == 'STATUS_CANCELED':
                self._handlers.pop(request_id)
                logger.info(f"Request {request_id} deleted because server cant find it")

            elif response_text.startswith('STATUS_OK'):
                sms_code = response_text.split(':')[1]
                handler_params = self._handlers[request_id]
                handler, args, kwargs = handler_params
                asyncio.create_task(handler(sms_code, *args, **kwargs))
            elif response_text.startswith('STATUS_WAIT_RETRY'):
                sms_code = response_text.split(':')[1]
                handler_params = self._handlers[request_id]
                handler, args, kwargs = handler_params
                asyncio.create_task(handler(sms_code, *args, **kwargs))

    async def polling(self, gap: int = 30):
        '''Send request to server every 30 seconds.
        If response have data about new SMS, calling appropriate handler
        from TeamPro._handlers
        :param gap: interval between requests in seconds'''
        while True:
            await asyncio.gather(*[self._check_sms(request_id) for request_id in self._handlers.keys()])
            await asyncio.sleep(gap)

    def __str__(self):
        return 'Drop SMS'