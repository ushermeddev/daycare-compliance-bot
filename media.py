"""
LINE media download utility.
Downloads binary content (audio, image) from LINE's blob API.
"""
import os
from linebot.v3.messaging import AsyncApiClient, AsyncMessagingApiBlob, Configuration

_config = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""))


async def download_content(message_id: str) -> bytes:
    """
    Download message media from LINE and return raw bytes.
    Works for both audio (.m4a) and image (JPEG) messages.
    """
    async with AsyncApiClient(_config) as client:
        blob = AsyncMessagingApiBlob(client)
        response = await blob.get_message_content(message_id=message_id)
        # LINE SDK v3 returns an httpx.Response; .content is the raw bytes
        if hasattr(response, "content"):
            return response.content
        # Fallback: already bytes
        return bytes(response)
