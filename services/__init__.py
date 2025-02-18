from .base import BaseService
from .sms_activate import SMSActivateService
from .sms_hub import SmsHubService
from .drop_sms_bot import DropSmsService
from .sms_man.sms_man import SmsManServices
from .viotp import ViotpService
from .five_sim import FiveSimService
from .sms_activation_pro.sms_activation_pro import SmsActivationPro
import json
from os.path import abspath

FILEPATH = abspath(r'services/services.json')

services: list[BaseService] = [SMSActivateService(), SmsHubService(), DropSmsService(), SmsManServices(),
                               ViotpService(), FiveSimService()]

with open(FILEPATH, 'r', encoding='utf-8') as fp:
    data = json.load(fp)
all_services: list[str] = data['all_services']
all_countries: list[str] = data['all_countries']
