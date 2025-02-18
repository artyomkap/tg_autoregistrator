from abc import abstractmethod, ABC
from typing import Callable, Optional


class ServerUnavailable(BaseException):
    pass


class BadAPIKey(BaseException):
    pass


class BaseService(ABC):
    '''get interface to interact with services that take SMS.
    If your class needed to execute asynchronous code before (and after) use,
    you may implement async method 'connect' and async 'close' - they will be called before(and after accordingly) any others methods'''

    @abstractmethod
    async def get_balance(self) -> int:
        '''return actual balance'''

    @abstractmethod
    async def get_countries(self) -> dict[str, str]:  # dict as: country title: country id
        '''return available countries. May be raise ServerUnavailable exception'''

    @abstractmethod
    async def get_services(self) -> dict[str, str]:
        '''return available services. May be raise ServerUnavailable exception'''

    @abstractmethod
    async def rent_number(self, country_id: str, service_id: str, handler: Callable[[str], None], *args, **kwargs):
        '''rent a number from service. May be raise ServerUnavailable exception
    :param handler: async function. Call when
    sms is received with (msg[msg code as str], *args, **kwargs)'''

    @abstractmethod
    async def get_price(self, country_id: str, service_id: str) -> int:
        '''get price for current country and service. If service not have required telephone
        numbers, method must be raise ServerUnavailable exception.'''
