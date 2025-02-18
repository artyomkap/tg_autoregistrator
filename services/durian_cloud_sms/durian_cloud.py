import asyncio
import logging
from services.base import BaseService, ServerUnavailable, BadAPIKey
from typing import Callable
from config import config
import aiohttp
import json
import datetime as dt
from . import durian_cloud_countries, durian_cloud_services


logger = logging.getLogger(__name__)


class DurianCloudService(BaseService):
    MAX_CACHING_TIME = 12  # in hours
    api_key = config['api_keys']['durian_cloud']
    _api_url = 'https://api.duraincloud.com/out/ext_api/'
    _handlers: dict[int, tuple[Callable, list, dict]] = {}


    def __init__(self):
        self._countries = durian_cloud_countries.countries
        self._services = durian_cloud_services.services


    async def connect(self):
        self.aiohttp_session = aiohttp.ClientSession()
        self.polling_task = asyncio.create_task(self.polling())


    async def polling(self, gap: int = 30):
        '''Send request to server every 30 seconds.
        If response have data about new SMS, calling appropriate handler
        from DurianCloud._handlers
        :param gap: interval between requests in seconds'''
        while True:
            await asyncio.gather(*[self._check_sms(phone_number, service_id) for phone_number, service_id in self._handlers.keys()])
            await asyncio.sleep(gap)

    async def close(self):
        self.polling_task.cancel()
        await self.aiohttp_session.close()

    async def get_balance(self) -> None:
        '''Request for getting a balance for Durian Cloud Service
        The API Request is not on the website.'''
        return None

    async def get_countries(self) -> dict[str, str]:
        return self._countries


    async def get_services(self) -> dict[str, str]:
        return self._services


    async def get_price(self, country_id: str, service_id: str) -> float:
        return 0.08


    async def rent_number(self, country_id: str, service_id: str, handler: Callable[[str], None], *args,
                    **kwargs) -> str:
        if not (country_id in (await self.get_countries()).values() and service_id in (
                await self.get_services()).values()):
            raise ValueError('Unsupported country_id or value_id')
        url = self._api_url + 'getMobile'
        payload = {
            'name': 'admin',
            'ApiKey': self.api_key,
            'cuy': country_id,
            'pid': service_id,
            'num': '1',
            'noblack': '0',
            'serial': '2',
            'secret_key': 'null',
            'vip': 'null'
        }
        async with self.aiohttp_session.get(url, params=payload) as response:
            response_text = await response.text()
            try:
                data = await response.json()
                phone_number = data['data']
            except (KeyError, ValueError):
                raise ServerUnavailable("Failed to retrieve phone number from the server")
            self._handlers[(phone_number, service_id)] = (handler, (phone_number, service_id), kwargs)

            return phone_number

    async def _check_sms(self, phone_number, service_id) -> None:
        url = self._api_url + 'getMsg'
        payload = {'name': 'admin', 'ApiKey': self.api_key, 'pn': phone_number, 'pid': service_id, 'serial': '2'}
        async with self.aiohttp_session.get(url, params=payload) as response:
            response_text = await response.text()
            try:
                data = await response.json()
                sms_data = data['data']
                handler_params = self._handlers[phone_number, service_id]
                handler, args, kwargs = handler_params
                asyncio.create_task(handler(sms_data, *args, **kwargs))
            except (KeyError, ValueError):
                raise ServerUnavailable("Failed to retrieve phone number from the server")



    def __str__(self):
        return 'Durian Cloud Sms'
