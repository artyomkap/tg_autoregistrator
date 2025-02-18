from fastapi import APIRouter
import logging
from config import config
from services.viotp.viotp import ViotpService
from pydantic import BaseModel


class ViotpWebhook(BaseModel):
    activationId: int
    service: str
    text: str
    code: str
    receivedAt: str


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(config['web_server']['viotp_webhook_path'])
async def sms_activate_webhook(request: ViotpWebhook):
    data = ViotpService._handlers.get(request.activationId, None)
    if not data:
        logger.warning(f"Unknown activationId: {request.activationId}")
        return
    task = data[0](request.text, *data[1], **data[2])
    await task
