from typing import TypedDict

from secure import Secure
from secure.headers import (
    CacheControl,
    ContentSecurityPolicy,
    CrossOriginOpenerPolicy,
    ReferrerPolicy,
    Server,
    StrictTransportSecurity,
    XContentTypeOptions,
    XFrameOptions,
    PermissionsPolicy
)

class HeadersParameters(TypedDict, total=False):
    cache: CacheControl
    coop: CrossOriginOpenerPolicy
    hsts: StrictTransportSecurity
    referrer: ReferrerPolicy
    server: Server
    xcto: XContentTypeOptions
    xfo: XFrameOptions
    
headers_parameters: HeadersParameters = {
    'cache': CacheControl().no_store(),
    'coop': CrossOriginOpenerPolicy().same_origin(),
    'hsts': StrictTransportSecurity().max_age(31536000),
    'referrer': ReferrerPolicy().strict_origin_when_cross_origin(),
    'server': Server().set(""),
    'xcto': XContentTypeOptions().nosniff(),
    'xfo': XFrameOptions().sameorigin(),
}
csp_general = ContentSecurityPolicy().default_src(
        "'self'"
    ).script_src(
        "'self'"
    ).style_src(
        "'self'"
    ).object_src("'none'")
csp_permissive = ContentSecurityPolicy().default_src(
        "'self'"
    ).script_src(
        "'self' https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js"
    ).style_src(
        "'self' 'unsafe-inline'"
    ).object_src(
        "'none'"
    ).worker_src("blob:")
permissions_policy = PermissionsPolicy().geolocation().camera().microphone()

secure_headers = Secure(**headers_parameters, csp=csp_general, permissions=permissions_policy)
secure_headers_redoc = Secure(**headers_parameters, csp=csp_permissive, permissions=permissions_policy)
