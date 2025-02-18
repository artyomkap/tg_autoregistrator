import asyncio
import logging
from services.base import BaseService, ServerUnavailable, BadAPIKey
from typing import Callable
from config import config
import aiohttp
import json
import datetime as dt


logger = logging.getLogger(__name__)

class SmsManServices(BaseService):
    '''SMS Man service implementation'''

    MAX_CACHING_TIME = 12  # in hours
    api_key = config['api_keys']['sms_man']
    _api_url = 'https://api.sms-man.com/control/'
    _handlers: dict[int, tuple[Callable, list, dict]] = {}

    def __init__(self):
        self._countries = {}
        self._services = {}


    async def _check_sms(self, request_id) -> None:
        payload = {'token': self.api_key, 'request_id': request_id}
        async with self.aiohttp_session.get(f'{self._api_url}get-sms', params=payload) as response:
            response_text = await response.content.read()
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError:
                raise ServerUnavailable("Failed to parse server response")
            if 'error_code' in data:
                if data['error_msg'] == "Current request not exists":  # если истек срок действия номера
                    self._handlers.pop(request_id)  # то наличие смс на этом номере больше не проверяется
                    logger.info(f"Request {request_id} deleted because server cant find it")
                elif data['error_msg'] == "Still waiting...":
                    return
            else:
                handler_params = self._handlers[request_id]
                handler, args, kwargs = handler_params
                asyncio.create_task(handler(data['sms_code'], *args, **kwargs))
            

    async def polling(self, gap: int = 30):
        '''Send request to server every 30 seconds.
        If response have data about new SMS, calling appropriate handler 
        from SmsManService._handlers
        :param gap: interval between requests in seconds'''
        while True:
            await asyncio.gather(*[self._check_sms(request_id) for request_id in self._handlers.keys()])
            await asyncio.sleep(gap)

    async def connect(self):
        self.aiohttp_session = aiohttp.ClientSession()
        self.polling_task = asyncio.create_task(self.polling())

    async def get_balance(self) -> float:
        url = f'{self._api_url}get-balance'
        payload = {'token': self.api_key}
        async with self.aiohttp_session.get(url, params=payload) as response:
            data = await response.json()
            if 'success' in data and data['success'] is False:
                error_code = data.get('error_code', 'unknown_error')
                error_msg = data.get('error_msg', 'Unknown error occurred.')
                if error_code == 'wrong_token':
                    raise BadAPIKey(error_msg)
                else:
                    raise ServerUnavailable("Server response not correct")
            elif 'balance' in data:
                return float(data['balance'])
            else:
                raise ServerUnavailable("Unexpected server response format.")

    async def get_countries(self) -> dict[str, str]:
        if not hasattr(self, 'last_countries_update_time'):
            self.last_countries_update_time = dt.datetime(year=2000, month=1, day=1)
        if dt.datetime.now() - self.last_countries_update_time < dt.timedelta(hours=self.MAX_CACHING_TIME):
            return self._countries
        self.last_countries_update_time = dt.datetime.now()
        url = f'{self._api_url}countries'
        payload = {'token': self.api_key}
        async with self.aiohttp_session.get(url, params=payload) as response:
            data = await response.json()
            try:
                countries = {country['title']: (country['id']) for country in data.values()}
                self._countries = countries
                return countries
            except (KeyError, TypeError):
                raise ServerUnavailable("Server response not correct")

    async def get_services(self) -> dict[str, str]:
        if not hasattr(self, 'last_services_update_time'):
            self.last_services_update_time = dt.datetime(year=2000, month=1, day=1)
        if dt.datetime.now() - self.last_services_update_time < dt.timedelta(hours=self.MAX_CACHING_TIME):
            return self._services
        self.last_services_update_time = dt.datetime.now()
        url = f'{self._api_url}applications'
        payload = {'token': self.api_key}
        async with self.aiohttp_session.get(url, params=payload) as response:
            data = await response.json()
            try:
                services = {service['title']: (service['id']) for service in data.values()}
                self._services = services
                return services
            except (KeyError, TypeError):
                raise ServerUnavailable("Server response not correct")

    async def close(self):
        self.polling_task.cancel()
        await self.aiohttp_session.close()

    async def get_price(self, country_id: str, service_id: str) -> dict:
        if not country_id in (await self.get_countries()).values():
            raise ValueError('Unsupported country_id or value_id')

        url = f'{self._api_url}get-prices'
        payload = {'token': self.api_key, 'country_id': country_id}

        async with self.aiohttp_session.get(url, params=payload) as response:
            data = await response.text()
            try:
                prices = json.loads(data)
                formatted_prices = {}

                # Находим цену для конкретного сервиса и страны
                price_info = prices.get(service_id)
                if price_info:
                    cost = price_info['cost']
                    count = price_info['count']
                    formatted_prices[service_id] = {'cost': cost, 'count': count}
                else:
                    raise ValueError(f'Price info for service_id {service_id} not found')

                return cost
            except json.JSONDecodeError:
                raise ServerUnavailable("Failed to decode server response")


    async def rent_number(self, country_id: str, service_id: str, handler: Callable[[str], None], *args, **kwargs):
        if not (country_id in (await self.get_countries()).values() and service_id in (
        await self.get_services()).values()):
            raise ValueError('Unsupported country_id or value_id')
        url = f'{self._api_url}get-number'
        payload = {'token': self.api_key, 'country_id': country_id, 'application_id': service_id}
        async with self.aiohttp_session.get(url, params=payload) as response:
            response_text = await response.text()
            if not response_text:
                raise ServerUnavailable("Server response is empty")

            try:
                data = json.loads(response_text)
                if 'error_code' in data and data['error_code'] == 'balance':
                    raise ServerUnavailable(data['error_msg'])

                activation_id = data.get('request_id')
                phone_number = data.get('number')
            except (json.JSONDecodeError, KeyError):
                raise ServerUnavailable("Failed to parse server response")

        self._handlers[activation_id] = (handler, args, kwargs)
        return phone_number

    def __str__(self):
        return 'Sms Man'