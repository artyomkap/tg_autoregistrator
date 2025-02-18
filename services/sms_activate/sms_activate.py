from services.base import BaseService, ServerUnavailable, BadAPIKey
from typing import Callable
from config import config
import aiohttp
import json
from . import sms_activate_services
import datetime as dt


class SMSActivateService(BaseService):
    '''SMS Activate service implementation'''

    MAX_CACHING_TIME = 12  # in hours
    api_key = config['api_keys']['sms_activate']
    _api_url = 'https://api.sms-activate.org/stubs/handler_api.php'
    _handlers: dict[int, tuple[Callable, list, dict]] = {}

    def __init__(self):
        self._counties = {}
        self._services = sms_activate_services.services

    async def connect(self):
        self.aiohttp_session = aiohttp.ClientSession()

    async def get_balance(self) -> int:
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
        if not hasattr(self, 'last_countries_update_time'):
            self.last_countries_update_time = dt.datetime(year=2000, month=1, day=1)
        if dt.datetime.now() - self.last_countries_update_time < dt.timedelta(hours=self.MAX_CACHING_TIME):
            return self._counties
        self.last_countries_update_time = dt.datetime.now()
        payload = {'api_key': self.api_key, 'action': 'getCountries'}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            data = await response.content.read()
            if data == 'BAD_KEY':
                raise BadAPIKey
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                raise ServerUnavailable("Server response not correct")
        self._counties = {v['eng']: k for k, v in data.items() if v['rent'] == 1}  # only available
        return self._counties

    async def get_services(self) -> dict[str, str]:
        return self._services

    async def close(self):
        await self.aiohttp_session.close()

    async def rent_number(self, country_id: str, service_id: str, handler: Callable[[str], None], *args,
                          **kwargs) -> str:
        if not (country_id in (await self.get_countries()).values() and service_id in (
        await self.get_services()).values()):
            raise ValueError('Unsupported country_id or value_id')
        payload = {'api_key': self.api_key, 'service': service_id, 'country': country_id, 'action': 'getNumberV2'}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            response = await response.content.read()
            try:
                data = json.loads(response)
                activation_id = data['activationId']
            except (json.JSONDecodeError, KeyError):
                raise ServerUnavailable
        self._handlers[activation_id] = (handler, args, kwargs)
        return data['phoneNumber']

    async def get_price(self, country_id: str, service_id: str) -> int:
        payload = {'api_key': self.api_key, 'service': service_id, 'country': country_id, 'action': 'getPrices'}
        async with self.aiohttp_session.get(self._api_url, params=payload) as response:
            response = await response.content.read()
            try:
                data = json.loads(response)
                country = data[country_id]
                price = country[service_id]['cost']
                count = data[country_id][service_id]['count']
            except (json.JSONDecodeError, KeyError):
                raise ServerUnavailable
        if count == 0:
            raise ServerUnavailable
        return price

    def __str__(self):
        return 'SMS Activate'
