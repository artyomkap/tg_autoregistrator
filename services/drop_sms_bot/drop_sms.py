import asyncio
import logging

from services.base import BaseService, ServerUnavailable, BadAPIKey
from typing import Callable
from config import config
import aiohttp
import json
import datetime as dt
from services.drop_sms_bot import drop_sms_services, drop_sms_countries


logger = logging.getLogger(__name__)

class DropSmsService(BaseService):

    MAX_CACHING_TIME = 12  # in hours
    api_key = config['api_keys']['drop_sms']
    _api_url = 'https://api.dropsms.cc/stubs/handler_api.php'
    _handlers: dict[int, tuple[Callable, list, dict]] = {}

    def __init__(self):
        self._countries = drop_sms_countries.countries
        self._services = drop_sms_services.services
        self.aiohttp_session = aiohttp.ClientSession()

    async def _check_sms(self, request_id) -> None:
        payload = {'action': 'getStatus', 'api_key': self.api_key, 'id': request_id}
        async with self.aiohttp_session.get(url=self._api_url, params=payload) as response:
            response_text = await response.text()
            if not response_text:
                raise ServerUnavailable("Empty response from server")
            try:
                data = json.loads(response_text)
                print(data)
            except json.JSONDecodeError:
                raise ServerUnavailable("Failed to parse server response")
            if 'error_code' in data:
                if data['error_msg'] == "Current request not exists":  # если истек срок действия номера
                    self._handlers.pop(request_id)  # то наличие смс на этом номере больше не проверяется
                    logger.info(f"Request {request_id} deleted because server cant find it")
                elif data['error_msg'] == "Still waiting...":
                    return

    async def polling(self, gap: int = 30):
        '''Send request to server every 30 seconds.
        If response have data about new SMS, calling appropriate handler
        from DropSms._handlers
        :param gap: interval between requests in seconds'''
        while True:
            await asyncio.gather(*[self._check_sms(request_id) for request_id in self._handlers.keys()])
            await asyncio.sleep(gap)

    async def connect(self):
        self.aiohttp_session = aiohttp.ClientSession()
        self.polling_task = asyncio.create_task(self.polling())

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

    async def close(self):
        self.polling_task.cancel()
        await self.aiohttp_session.close()

    async def get_price(self, country_id: str, service_id: str) -> float:
        if service_id == 'vk':
            return 0.06
        elif service_id == 'fb' or service_id == 'go' or service_id == 'ig':
            return 0.01
        elif service_id == 'wa':
            return 0.14
        else:
            raise ValueError('Unsupported country_id or value_id')


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
            try:
                data = json.loads(response_text)
                if 'response' in data and data['response'] == 'NO_BALANCE':
                    raise ServerUnavailable("Insufficient balance to rent number")
                activation_id = data['activationId']
            except (json.JSONDecodeError, KeyError):
                raise ServerUnavailable
        self._handlers[activation_id] = (handler, args, kwargs)
        return data['phoneNumber']

    def __str__(self):
        return 'Drop SMS'

