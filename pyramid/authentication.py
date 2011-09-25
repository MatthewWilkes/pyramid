from codecs import utf_8_decode
from codecs import utf_8_encode
from hashlib import md5
import base64
import datetime
import re
import time as time_mod

from zope.interface import implementer

from pyramid.compat import long
from pyramid.compat import text_type
from pyramid.compat import binary_type
from pyramid.compat import url_unquote
from pyramid.compat import url_quote
from pyramid.compat import bytes_

from pyramid.interfaces import IAuthenticationPolicy
from pyramid.interfaces import IDebugLogger

from pyramid.security import Authenticated
from pyramid.security import Everyone

VALID_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9+_-]*$")

class CallbackAuthenticationPolicy(object):
    """ Abstract class """

    debug = False
    callback = None

    def _log(self, msg, methodname, request):
        logger = request.registry.queryUtility(IDebugLogger)
        if logger:
            cls = self.__class__
            classname = cls.__module__ + '.' + cls.__name__
            methodname = classname + '.' + methodname
            logger.debug(methodname + ': ' + msg)

    def authenticated_userid(self, request):
        debug = self.debug
        userid = self.unauthenticated_userid(request)
        if userid is None:
            debug and self._log(
                'call to unauthenticated_userid returned None; returning None',
                'authenticated_userid',
                request)
            return None
        if self.callback is None:
            debug and self._log(
                'there was no groupfinder callback; returning %r' % (userid,),
                'authenticated_userid',
                request)
            return userid
        callback_ok = self.callback(userid, request)
        if callback_ok is not None: # is not None!
            debug and self._log(
                'groupfinder callback returned %r; returning %r' % (
                    callback_ok, userid),
                'authenticated_userid',
                request
                )
            return userid
        debug and self._log(
            'groupfinder callback returned None; returning None',
            'authenticated_userid',
            request
            )

    def effective_principals(self, request):
        debug = self.debug
        effective_principals = [Everyone]
        userid = self.unauthenticated_userid(request)
        if userid is None:
            debug and self._log(
                'authenticated_userid returned %r; returning %r' % (
                    userid, effective_principals),
                'effective_principals',
                request
                )
            return effective_principals
        if self.callback is None:
            debug and self._log(
                'groupfinder callback is None, so groups is []',
                'effective_principals',
                request)
            groups = []
        else:
            groups = self.callback(userid, request)
            debug and self._log(
                'groupfinder callback returned %r as groups' % (groups,),
                'effective_principals',
                request)
        if groups is None: # is None!
            debug and self._log(
                'returning effective principals: %r' % (
                    effective_principals,),
                'effective_principals',
                request
                )
            return effective_principals

        effective_principals.append(Authenticated)
        effective_principals.append(userid)
        effective_principals.extend(groups)

        debug and self._log(
            'returning effective principals: %r' % (
                effective_principals,),
            'effective_principals',
            request
             )
        return effective_principals

@implementer(IAuthenticationPolicy)
class RepozeWho1AuthenticationPolicy(CallbackAuthenticationPolicy):
    """ A :app:`Pyramid` :term:`authentication policy` which
    obtains data from the :mod:`repoze.who` 1.X WSGI 'API' (the
    ``repoze.who.identity`` key in the WSGI environment).

    Constructor Arguments

    ``identifier_name``

       Default: ``auth_tkt``.  The :mod:`repoze.who` plugin name that
       performs remember/forget.  Optional.

    ``callback``

        Default: ``None``.  A callback passed the :mod:`repoze.who` identity
        and the :term:`request`, expected to return ``None`` if the user
        represented by the identity doesn't exist or a sequence of principal
        identifiers (possibly empty) representing groups if the user does
        exist.  If ``callback`` is None, the userid will be assumed to exist
        with no group principals.

    Objects of this class implement the interface described by
    :class:`pyramid.interfaces.IAuthenticationPolicy`.
    """

    def __init__(self, identifier_name='auth_tkt', callback=None):
        self.identifier_name = identifier_name
        self.callback = callback

    def _get_identity(self, request):
        return request.environ.get('repoze.who.identity')

    def _get_identifier(self, request):
        plugins = request.environ.get('repoze.who.plugins')
        if plugins is None:
            return None
        identifier = plugins[self.identifier_name]
        return identifier

    def authenticated_userid(self, request):
        identity = self._get_identity(request)
        if identity is None:
            return None
        if self.callback is None:
            return identity['repoze.who.userid']
        if self.callback(identity, request) is not None: # is not None!
            return identity['repoze.who.userid']

    def unauthenticated_userid(self, request):
        identity = self._get_identity(request)
        if identity is None:
            return None
        return identity['repoze.who.userid']

    def effective_principals(self, request):
        effective_principals = [Everyone]
        identity = self._get_identity(request)
        if identity is None:
            return effective_principals
        if self.callback is None:
            groups = []
        else:
            groups = self.callback(identity, request)
        if groups is None: # is None!
            return effective_principals
        userid = identity['repoze.who.userid']
        effective_principals.append(Authenticated)
        effective_principals.append(userid)
        effective_principals.extend(groups)

        return effective_principals

    def remember(self, request, principal, **kw):
        identifier = self._get_identifier(request)
        if identifier is None:
            return []
        environ = request.environ
        identity = {'repoze.who.userid':principal}
        return identifier.remember(environ, identity)

    def forget(self, request):
        identifier = self._get_identifier(request)
        if identifier is None:
            return []
        identity = self._get_identity(request)
        return identifier.forget(request.environ, identity)

@implementer(IAuthenticationPolicy)
class RemoteUserAuthenticationPolicy(CallbackAuthenticationPolicy):
    """ A :app:`Pyramid` :term:`authentication policy` which
    obtains data from the ``REMOTE_USER`` WSGI environment variable.

    Constructor Arguments

    ``environ_key``

        Default: ``REMOTE_USER``.  The key in the WSGI environ which
        provides the userid.

    ``callback``

        Default: ``None``.  A callback passed the userid and the request,
        expected to return None if the userid doesn't exist or a sequence of
        principal identifiers (possibly empty) representing groups if the
        user does exist.  If ``callback`` is None, the userid will be assumed
        to exist with no group principals.

    ``debug``

        Default: ``False``.  If ``debug`` is ``True``, log messages to the
        Pyramid debug logger about the results of various authentication
        steps.  The output from debugging is useful for reporting to maillist
        or IRC channels when asking for support.

    Objects of this class implement the interface described by
    :class:`pyramid.interfaces.IAuthenticationPolicy`.
    """

    def __init__(self, environ_key='REMOTE_USER', callback=None, debug=False):
        self.environ_key = environ_key
        self.callback = callback
        self.debug = debug

    def unauthenticated_userid(self, request):
        return request.environ.get(self.environ_key)

    def remember(self, request, principal, **kw):
        return []

    def forget(self, request):
        return []

@implementer(IAuthenticationPolicy)
class AuthTktAuthenticationPolicy(CallbackAuthenticationPolicy):
    """ A :app:`Pyramid` :term:`authentication policy` which
    obtains data from an :class:`paste.auth.auth_tkt` cookie.

    Constructor Arguments

    ``secret``

       The secret (a string) used for auth_tkt cookie signing.
       Required.

    ``callback``

       Default: ``None``.  A callback passed the userid and the
       request, expected to return ``None`` if the userid doesn't
       exist or a sequence of principal identifiers (possibly empty) if
       the user does exist.  If ``callback`` is ``None``, the userid
       will be assumed to exist with no principals.  Optional.

    ``cookie_name``

       Default: ``auth_tkt``.  The cookie name used
       (string).  Optional.

    ``secure``

       Default: ``False``.  Only send the cookie back over a secure
       conn.  Optional.

    ``include_ip``

       Default: ``False``.  Make the requesting IP address part of
       the authentication data in the cookie.  Optional.

    ``timeout``

       Default: ``None``.  Maximum number of seconds which a newly
       issued ticket will be considered valid.  After this amount of
       time, the ticket will expire (effectively logging the user
       out).  If this value is ``None``, the ticket never expires.
       Optional.

    ``reissue_time``

       Default: ``None``.  If this parameter is set, it represents the number
       of seconds that must pass before an authentication token cookie is
       automatically reissued as the result of a request which requires
       authentication.  The duration is measured as the number of seconds
       since the last auth_tkt cookie was issued and 'now'.  If this value is
       ``0``, a new ticket cookie will be reissued on every request which
       requires authentication.

       A good rule of thumb: if you want auto-expired cookies based on
       inactivity: set the ``timeout`` value to 1200 (20 mins) and set the
       ``reissue_time`` value to perhaps a tenth of the ``timeout`` value
       (120 or 2 mins).  It's nonsensical to set the ``timeout`` value lower
       than the ``reissue_time`` value, as the ticket will never be reissued
       if so.  However, such a configuration is not explicitly prevented.

       Optional.

    ``max_age``

       Default: ``None``.  The max age of the auth_tkt cookie, in
       seconds.  This differs from ``timeout`` inasmuch as ``timeout``
       represents the lifetime of the ticket contained in the cookie,
       while this value represents the lifetime of the cookie itself.
       When this value is set, the cookie's ``Max-Age`` and
       ``Expires`` settings will be set, allowing the auth_tkt cookie
       to last between browser sessions.  It is typically nonsensical
       to set this to a value that is lower than ``timeout`` or
       ``reissue_time``, although it is not explicitly prevented.
       Optional.

    ``path``
 
       Default: ``/``. The path for which the auth_tkt cookie is valid.
       May be desirable if the application only serves part of a domain.
       Optional.
 
    ``http_only``
 
       Default: ``False``. Hide cookie from JavaScript by setting the
       HttpOnly flag. Not honored by all browsers.
       Optional.

    ``wild_domain``

       Default: ``True``. An auth_tkt cookie will be generated for the
       wildcard domain.
       Optional.

    ``debug``

        Default: ``False``.  If ``debug`` is ``True``, log messages to the
        Pyramid debug logger about the results of various authentication
        steps.  The output from debugging is useful for reporting to maillist
        or IRC channels when asking for support.

    Objects of this class implement the interface described by
    :class:`pyramid.interfaces.IAuthenticationPolicy`.
    """
    def __init__(self,
                 secret,
                 callback=None,
                 cookie_name='auth_tkt',
                 secure=False,
                 include_ip=False,
                 timeout=None,
                 reissue_time=None,
                 max_age=None,
                 path="/",
                 http_only=False,
                 wild_domain=True,
                 debug=False,
                 ):
        self.cookie = AuthTktCookieHelper(
            secret,
            cookie_name=cookie_name,
            secure=secure,
            include_ip=include_ip,
            timeout=timeout,
            reissue_time=reissue_time,
            max_age=max_age,
            http_only=http_only,
            path=path,
            wild_domain=wild_domain,
            )
        self.callback = callback
        self.debug = debug

    def unauthenticated_userid(self, request):
        result = self.cookie.identify(request)
        if result:
            return result['userid']

    def remember(self, request, principal, **kw):
        """ Accepts the following kw args: ``max_age``."""
        return self.cookie.remember(request, principal, **kw)

    def forget(self, request):
        return self.cookie.forget(request)

def b64encode(v):
    return base64.b64encode(bytes_(v)).strip().replace(b'\n', b'')

def b64decode(v):
    return base64.b64decode(bytes_(v))

# this class licensed under the MIT license (stolen from Paste)
class AuthTicket(object):
    """
    This class represents an authentication token.  You must pass in
    the shared secret, the userid, and the IP address.  Optionally you
    can include tokens (a list of strings, representing role names),
    'user_data', which is arbitrary data available for your own use in
    later scripts.  Lastly, you can override the cookie name and
    timestamp.

    Once you provide all the arguments, use .cookie_value() to
    generate the appropriate authentication ticket.

    CGI usage::

        token = auth_tkt.AuthTick('sharedsecret', 'username',
            os.environ['REMOTE_ADDR'], tokens=['admin'])
        print 'Status: 200 OK'
        print 'Content-type: text/html'
        print token.cookie()
        print
        ... redirect HTML ...

    Webware usage::

        token = auth_tkt.AuthTick('sharedsecret', 'username',
            self.request().environ()['REMOTE_ADDR'], tokens=['admin'])
        self.response().setCookie('auth_tkt', token.cookie_value())
    """

    def __init__(self, secret, userid, ip, tokens=(), user_data='',
                 time=None, cookie_name='auth_tkt',
                 secure=False):
        self.secret = secret
        self.userid = userid
        self.ip = ip
        self.tokens = ','.join(tokens)
        self.user_data = user_data
        if time is None:
            self.time = time_mod.time()
        else:
            self.time = time
        self.cookie_name = cookie_name
        self.secure = secure

    def digest(self):
        return calculate_digest(
            self.ip, self.time, self.secret, self.userid, self.tokens,
            self.user_data)

    def cookie_value(self):
        v = '%s%08x%s!' % (self.digest(), int(self.time),
                           url_quote(self.userid))
        if self.tokens:
            v += self.tokens + '!'
        v += self.user_data
        return v

# this class licensed under the MIT license (stolen from Paste)
class BadTicket(Exception):
    """
    Exception raised when a ticket can't be parsed.  If we get far enough to
    determine what the expected digest should have been, expected is set.
    This should not be shown by default, but can be useful for debugging.
    """
    def __init__(self, msg, expected=None):
        self.expected = expected
        Exception.__init__(self, msg)

# this function licensed under the MIT license (stolen from Paste)
def parse_ticket(secret, ticket, ip):
    """
    Parse the ticket, returning (timestamp, userid, tokens, user_data).

    If the ticket cannot be parsed, a ``BadTicket`` exception will be raised
    with an explanation.
    """
    ticket = ticket.strip('"')
    digest = ticket[:32]
    try:
        timestamp = int(ticket[32:40], 16)
    except ValueError as e:
        raise BadTicket('Timestamp is not a hex integer: %s' % e)
    try:
        userid, data = ticket[40:].split('!', 1)
    except ValueError:
        raise BadTicket('userid is not followed by !')
    userid = url_unquote(userid)
    if '!' in data:
        tokens, user_data = data.split('!', 1)
    else: # pragma: no cover (never generated)
        # @@: Is this the right order?
        tokens = ''
        user_data = data

    expected = calculate_digest(ip, timestamp, secret,
                                userid, tokens, user_data)

    if expected != digest:
        raise BadTicket('Digest signature is not correct',
                        expected=(expected, digest))

    tokens = tokens.split(',')

    return (timestamp, userid, tokens, user_data)

# this function licensed under the MIT license (stolen from Paste)
def calculate_digest(ip, timestamp, secret, userid, tokens, user_data):
    secret = bytes_(secret, 'utf-8')
    userid = bytes_(userid, 'utf-8')
    tokens = bytes_(tokens, 'utf-8')
    user_data = bytes_(user_data, 'utf-8')
    digest0 = md5(
        encode_ip_timestamp(ip, timestamp) + secret + userid + b'\0'
        + tokens + b'\0' + user_data).hexdigest()
    digest = md5(bytes_(digest0) + secret).hexdigest()
    return digest

# this function licensed under the MIT license (stolen from Paste)
def encode_ip_timestamp(ip, timestamp):
    ip_chars = ''.join(map(chr, map(int, ip.split('.'))))
    t = int(timestamp)
    ts = ((t & 0xff000000) >> 24,
          (t & 0xff0000) >> 16,
          (t & 0xff00) >> 8,
          t & 0xff)
    ts_chars = ''.join(map(chr, ts))
    return bytes_(ip_chars + ts_chars)

EXPIRE = object()

class AuthTktCookieHelper(object):
    """
    A helper class for use in third-party authentication policy
    implementations.  See
    :class:`pyramid.authentication.AuthTktAuthenticationPolicy` for the
    meanings of the constructor arguments.
    """
    parse_ticket = staticmethod(parse_ticket) # for tests
    AuthTicket = AuthTicket # for tests
    BadTicket = BadTicket # for tests
    now = None # for tests

    userid_type_decoders = {
        'int':int,
        'unicode':lambda x: utf_8_decode(x)[0], # bw compat for old cookies
        'b64unicode': lambda x: utf_8_decode(b64decode(x))[0],
        'b64str': lambda x: b64decode(x),
        }

    userid_type_encoders = {
        int: ('int', str),
        long: ('int', str),
        text_type: ('b64unicode', lambda x: b64encode(utf_8_encode(x)[0])),
        binary_type: ('b64str', lambda x: b64encode(x)),
        }
    
    def __init__(self, secret, cookie_name='auth_tkt', secure=False,
                 include_ip=False, timeout=None, reissue_time=None,
                 max_age=None, http_only=False, path="/", wild_domain=True):
        self.secret = secret
        self.cookie_name = cookie_name
        self.include_ip = include_ip
        self.secure = secure
        self.timeout = timeout
        self.reissue_time = reissue_time
        self.max_age = max_age
        self.http_only = http_only
        self.path = path
        self.wild_domain = wild_domain

        static_flags = []
        if self.secure:
            static_flags.append('; Secure')
        if self.http_only:
            static_flags.append('; HttpOnly')
        self.static_flags = "".join(static_flags)

    def _get_cookies(self, environ, value, max_age=None):
        if max_age is EXPIRE:
            max_age = "; Max-Age=0; Expires=Wed, 31-Dec-97 23:59:59 GMT"
        elif max_age is not None:
            later = datetime.datetime.utcnow() + datetime.timedelta(
                seconds=int(max_age))
            # Wdy, DD-Mon-YY HH:MM:SS GMT
            expires = later.strftime('%a, %d %b %Y %H:%M:%S GMT')
            # the Expires header is *required* at least for IE7 (IE7 does
            # not respect Max-Age)
            max_age = "; Max-Age=%s; Expires=%s" % (max_age, expires)
        else:
            max_age = ''

        cur_domain = environ.get('HTTP_HOST', environ.get('SERVER_NAME'))

        # While Chrome, IE, and Firefox can cope, Opera (at least) cannot
        # cope with a port number in the cookie domain when the URL it
        # receives the cookie from does not also have that port number in it
        # (e.g via a proxy).  In the meantime, HTTP_HOST is sent with port
        # number, and neither Firefox nor Chrome do anything with the
        # information when it's provided in a cookie domain except strip it
        # out.  So we strip out any port number from the cookie domain
        # aggressively to avoid problems.  See also
        # https://github.com/Pylons/pyramid/issues/131
        if ':' in cur_domain:
            cur_domain = cur_domain.split(':', 1)[0]

        cookies = [
            ('Set-Cookie', '%s="%s"; Path=%s%s%s' % (
            self.cookie_name, value, self.path, max_age, self.static_flags)),
            ('Set-Cookie', '%s="%s"; Path=%s; Domain=%s%s%s' % (
            self.cookie_name, value, self.path, cur_domain, max_age,
                self.static_flags)),
            ]

        if self.wild_domain:
            wild_domain = '.' + cur_domain
            cookies.append(('Set-Cookie', '%s="%s"; Path=%s; Domain=%s%s%s' % (
                self.cookie_name, value, self.path, wild_domain, max_age,
                self.static_flags)))

        return cookies

    def identify(self, request):
        """ Return a dictionary with authentication information, or ``None``
        if no valid auth_tkt is attached to ``request``"""
        environ = request.environ
        cookie = request.cookies.get(self.cookie_name)

        if cookie is None:
            return None

        if self.include_ip:
            remote_addr = environ['REMOTE_ADDR']
        else:
            remote_addr = '0.0.0.0'
        
        try:
            timestamp, userid, tokens, user_data = self.parse_ticket(
                self.secret, cookie, remote_addr)
        except self.BadTicket:
            return None

        now = self.now # service tests

        if now is None: 
            now = time_mod.time()

        if self.timeout and ( (timestamp + self.timeout) < now ):
            # the auth_tkt data has expired
            return None

        userid_typename = 'userid_type:'
        user_data_info = user_data.split('|')
        for datum in filter(None, user_data_info):
            if datum.startswith(userid_typename):
                userid_type = datum[len(userid_typename):]
                decoder = self.userid_type_decoders.get(userid_type)
                if decoder:
                    userid = decoder(userid)

        reissue = self.reissue_time is not None

        if reissue and not hasattr(request, '_authtkt_reissued'):
            if ( (now - timestamp) > self.reissue_time ):
                # work around https://github.com/Pylons/pyramid/issues#issue/108
                tokens = list(filter(None, tokens))
                headers = self.remember(request, userid, max_age=self.max_age,
                                        tokens=tokens)
                def reissue_authtkt(request, response):
                    if not hasattr(request, '_authtkt_reissue_revoked'):
                        for k, v in headers:
                            response.headerlist.append((k, v))
                request.add_response_callback(reissue_authtkt)
                request._authtkt_reissued = True

        environ['REMOTE_USER_TOKENS'] = tokens
        environ['REMOTE_USER_DATA'] = user_data
        environ['AUTH_TYPE'] = 'cookie'

        identity = {}
        identity['timestamp'] = timestamp
        identity['userid'] = userid
        identity['tokens'] = tokens
        identity['userdata'] = user_data
        return identity

    def forget(self, request):
        """ Return a set of expires Set-Cookie headers, which will destroy
        any existing auth_tkt cookie when attached to a response"""
        environ = request.environ
        request._authtkt_reissue_revoked = True
        return self._get_cookies(environ, '', max_age=EXPIRE)
    
    def remember(self, request, userid, max_age=None, tokens=()):
        """ Return a set of Set-Cookie headers; when set into a response,
        these headers will represent a valid authentication ticket.

        ``max_age``
          The max age of the auth_tkt cookie, in seconds.  When this value is
          set, the cookie's ``Max-Age`` and ``Expires`` settings will be set,
          allowing the auth_tkt cookie to last between browser sessions.  If
          this value is ``None``, the ``max_age`` value provided to the
          helper itself will be used as the ``max_age`` value.  Default:
          ``None``.

        ``tokens``
          A sequence of strings that will be placed into the auth_tkt tokens
          field.  Each string in the sequence must be of the Python ``str``
          type and must match the regex ``^[A-Za-z][A-Za-z0-9+_-]*$``.
          Tokens are available in the returned identity when an auth_tkt is
          found in the request and unpacked.  Default: ``()``.
        """
        if max_age is None:
            max_age = self.max_age

        environ = request.environ

        if self.include_ip:
            remote_addr = environ['REMOTE_ADDR']
        else:
            remote_addr = '0.0.0.0'

        user_data = ''

        encoding_data = self.userid_type_encoders.get(type(userid))

        if encoding_data:
            encoding, encoder = encoding_data
            userid = encoder(userid)
            user_data = 'userid_type:%s' % encoding
        
        for token in tokens:
            if isinstance(token, text_type):
                try:
                    token.encode('ascii')
                except UnicodeEncodeError:
                    raise ValueError("Invalid token %r" % (token,))
            if not (isinstance(token, str) and VALID_TOKEN.match(token)):
                raise ValueError("Invalid token %r" % (token,))

        if hasattr(request, '_authtkt_reissued'):
            request._authtkt_reissue_revoked = True

        ticket = self.AuthTicket(
            self.secret,
            userid,
            remote_addr,
            tokens=tokens,
            user_data=user_data,
            cookie_name=self.cookie_name,
            secure=self.secure)

        cookie_value = ticket.cookie_value()
        return self._get_cookies(environ, cookie_value, max_age)

@implementer(IAuthenticationPolicy)
class SessionAuthenticationPolicy(CallbackAuthenticationPolicy):
    """ A :app:`Pyramid` authentication policy which gets its data from the
    configured :term:`session`.  For this authentication policy to work, you
    will have to follow the instructions in the :ref:`sessions_chapter` to
    configure a :term:`session factory`.

    Constructor Arguments

    ``prefix``

       A prefix used when storing the authentication parameters in the
       session. Defaults to 'auth.'. Optional.

    ``callback``

       Default: ``None``.  A callback passed the userid and the
       request, expected to return ``None`` if the userid doesn't
       exist or a sequence of principal identifiers (possibly empty) if
       the user does exist.  If ``callback`` is ``None``, the userid
       will be assumed to exist with no principals.  Optional.

    ``debug``

        Default: ``False``.  If ``debug`` is ``True``, log messages to the
        Pyramid debug logger about the results of various authentication
        steps.  The output from debugging is useful for reporting to maillist
        or IRC channels when asking for support.
       
    """

    def __init__(self, prefix='auth.', callback=None, debug=False):
        self.callback = callback
        self.prefix = prefix or ''
        self.userid_key = prefix + 'userid'
        self.debug = debug

    def remember(self, request, principal, **kw):
        """ Store a principal in the session."""
        request.session[self.userid_key] = principal
        return []

    def forget(self, request):
        """ Remove the stored principal from the session."""
        if self.userid_key in request.session:
            del request.session[self.userid_key]
        return []

    def unauthenticated_userid(self, request):
        return request.session.get(self.userid_key)

