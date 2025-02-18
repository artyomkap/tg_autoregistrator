import asyncio
import logging
from services.base import BaseService, ServerUnavailable, BadAPIKey
from typing import Callable
from config import config
import aiohttp
import json
import datetime as dt
from services.sms_hub import sms_hub_services, sms_hub_countries


logger = logging.getLogger(__name__)

class SmsHubService(BaseService):
    MAX_CACHING_TIME = 12  # in hours
    api_key = config['api_keys']['sms_hub']
    _api_url = 'https://smshub.org/stubs/handler_api.php'
    _handlers: dict[int, tuple[Callable, list, dict]] = {}

    def __init__(self):
        self._countries = sms_hub_countries.countries
        self._services = sms_hub_services.services


    async def _check_sms(self, request_id) -> None:
        payload = {'api_key': self.api_key, 'action': 'getStatus', 'id': request_id}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
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
        from SmsHub._handlers
        :param gap: interval between requests in seconds'''
        while True:
            await asyncio.gather(*[self._check_sms(request_id) for request_id in self._handlers.keys()])
            await asyncio.sleep(gap)


    async def connect(self):
        self.aiohttp_session = aiohttp.ClientSession()
        self.polling_task = asyncio.create_task(self.polling())

    async def get_balance(self) -> float:
        payload = {'api_key': self.api_key, 'action': 'getBalance'}
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

    async def rent_number(self, country_id: str, service_id: str, handler: Callable[[str], None], *args,
                          **kwargs) -> str:
        if not (country_id in (await self.get_countries()).values() and service_id in (
                await self.get_services()).values()):
            raise ValueError('Unsupported country_id or value_id')
        payload = {'api_key': self.api_key, 'action': 'getNumber', 'service': service_id, 'country': country_id}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            response_text = await response.text()
            if response_text.startswith("ACCESS_NUMBER:"):
                parts = response_text.split(":")
                activation_id = parts[1]
                phone_number = parts[2]
            else:
                raise ServerUnavailable
        self._handlers[activation_id] = (handler, args, kwargs)
        return phone_number

    async def get_price(self, country_id: str, service_id: str) -> int:
        payload = {'api_key': self.api_key, 'action': 'getPrices', 'service': service_id, 'country': country_id}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            response_text = await response.text()
            try:
                data = json.loads(response_text)
                price = data.get(country_id, {}).get(service_id, {}).get('Цена', 0)
                return int(price)
            except json.JSONDecodeError:
                raise ServerUnavailable

    async def close(self):
        self.polling_task.cancel()
        await self.aiohttp_session.close()



    def __str__(self):
        return 'Sms Hub'
