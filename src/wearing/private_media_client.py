"""Trusted connector-to-local-host lifecycle client; no media or user input."""
import json
from pathlib import Path
import ssl
from urllib.parse import urlsplit

import httpx

from .cloud.instance import read_private
from .device_gateway import DeviceGateway, GatewayError


class PrivateMediaClient:
    def __init__(self, config):
        self.config = config
        self.endpoint = str(config.get('endpoint','')).rstrip('/')
        url = urlsplit(self.endpoint)
        if (url.scheme not in ('http','https') or not url.hostname or url.username or url.password or
                url.path or url.query or url.fragment or
                (url.scheme=='http' and url.hostname not in ('127.0.0.1','::1','localhost'))):
            raise GatewayError('invalid_private_host_endpoint')
        if not isinstance(config.get('token'),str) or len(config['token'])<32:
            raise GatewayError('private_host_token_required')
        if url.scheme=='https':
            self.verify = ssl.create_default_context(cafile=config.get('ca_file'))
            if config.get('client_cert') or config.get('client_key'):
                self.verify.load_cert_chain(config['client_cert'],config['client_key'])
        else:
            self.verify = True

    @classmethod
    def from_path(cls, path):
        return cls(json.loads(read_private(Path(path))))

    def gateway(self):
        return DeviceGateway(self.config.get('gateway_root'),private_access_ready=True)

    async def request(self, method, path, body=None):
        try:
            async with httpx.AsyncClient(verify=self.verify,trust_env=False,timeout=12,
                                         follow_redirects=False) as client:
                result = await client.request(method,self.endpoint+path,
                                              headers={'Authorization':'Bearer '+self.config['token']},json=body)
                if result.status_code!=200 or len(result.content)>32768:
                    raise GatewayError('private_media_host_unavailable')
                return result.json()
        except (httpx.HTTPError,ValueError):
            raise GatewayError('private_media_host_unavailable') from None

    async def availability(self, resources):
        try:
            status = await self.request('GET','/v1/status')
            ready = set(status.get('resources',[])) if status.get('ready') is True else set()
        except GatewayError:
            ready = set()
        return {r['resource_id']:r['resource_id'] in ready for r in resources}

    async def clear(self, scope, session_id):
        epoch = self.gateway().snapshot(scope.resource_id)['epoch']
        result = await self.request('POST','/v1/clear',{'scope':vars(scope),'session_id':session_id,
                                                      'gateway_epoch':epoch})
        return (result.get('cleared') is True and result.get('session_id')==session_id and
                type(result.get('gateway_epoch')) is int and result['gateway_epoch']==epoch)
