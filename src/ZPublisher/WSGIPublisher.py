##############################################################################
#
# Copyright (c) 2002 Zope Foundation and Contributors.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
""" Python Object Publisher -- Publish Python objects on web servers
"""
from cStringIO import StringIO
import sys
import time

import transaction
from zExceptions import Redirect
from zExceptions import Unauthorized
from zope.event import notify
from zope.security.management import newInteraction, endInteraction
from zope.publisher.skinnable import setDefaultSkin
from ZServer.medusa.http_date import build_http_date

from ZPublisher.HTTPRequest import HTTPRequest
from ZPublisher.HTTPResponse import HTTPResponse
from ZPublisher.mapply import mapply
from ZPublisher import pubevents
from ZPublisher.Publish import call_object
from ZPublisher.Publish import dont_publish_class
from ZPublisher.Publish import get_module_info
from ZPublisher.Publish import missing_name
from ZPublisher.Iterators import IUnboundStreamIterator, IStreamIterator

_NOW = None  # overwrite for testing


def _now():
    if _NOW is not None:
        return _NOW
    return time.time()


class WSGIResponse(HTTPResponse):
    """A response object for WSGI

    This Response object knows nothing about ZServer, but tries to be
    compatible with the ZServerHTTPResponse.
    """
    _streaming = 0
    _http_version = None
    _server_version = None

    # Append any "cleanup" functions to this list.
    after_list = ()

    def finalize(self):

        headers = self.headers
        body = self.body

        # set 204 (no content) status if 200 and response is empty
        # and not streaming
        if ('content-type' not in headers and
                'content-length' not in headers and
                not self._streaming and self.status == 200):
            self.setStatus('nocontent')

        # add content length if not streaming
        content_length = headers.get('content-length')

        if content_length is None and not self._streaming:
            self.setHeader('content-length', len(body))

        return '%s %s' % (self.status, self.errmsg), self.listHeaders()

    def listHeaders(self):
        result = []
        if self._server_version:
            result.append(('Server', self._server_version))

        result.append(('Date', build_http_date(_now())))
        result.extend(HTTPResponse.listHeaders(self))
        return result

    def _unauthorized(self):
        self.setStatus(401)
        realm = self.realm
        if realm:
            self.setHeader('WWW-Authenticate', 'basic realm="%s"' % realm, 1)

    def write(self, data):
        """ Add data to our output stream.

        HTML data may be returned using a stream-oriented interface.
        This allows the browser to display partial results while
        computation of a response to proceed.
        """
        if not self._streaming:
            notify(pubevents.PubBeforeStreaming(self))
            self._streaming = 1
            self.stdout.flush()

        self.stdout.write(data)

    def setBody(self, body, title='', is_error=0):
        if isinstance(body, file):
            body.seek(0, 2)
            length = body.tell()
            body.seek(0)
            self.setHeader('Content-Length', '%d' % length)
            self.body = body
        elif IStreamIterator.providedBy(body):
            self.body = body
            HTTPResponse.setBody(self, '', title, is_error)
        elif IUnboundStreamIterator.providedBy(body):
            self.body = body
            self._streaming = 1
            HTTPResponse.setBody(self, '', title, is_error)
        else:
            HTTPResponse.setBody(self, body, title, is_error)

    def __str__(self):
        raise NotImplementedError


def publish(request, module_info, repoze_tm_active=False):
    (bobo_before,
     bobo_after,
     object,
     realm,
     debug_mode,
     err_hook,
     validated_hook,
     transactions_manager) = module_info

    notify(pubevents.PubStart(request))
    newInteraction()
    try:
        request.processInputs()
        response = request.response

        if bobo_after is not None:
            response.after_list += (bobo_after,)

        if debug_mode:
            response.debug_mode = debug_mode

        if realm and not request.get('REMOTE_USER', None):
            response.realm = realm

        if bobo_before is not None:
            bobo_before()

        # Get the path list.
        # According to RFC1738 a trailing space in the path is valid.
        path = request.get('PATH_INFO')

        request['PARENTS'] = [object]

        if not repoze_tm_active and transactions_manager:
            transactions_manager.begin()

        object = request.traverse(path, validated_hook=validated_hook)
        notify(pubevents.PubAfterTraversal(request))

        if transactions_manager:
            transactions_manager.recordMetaData(object, request)

        result = mapply(object,
                        request.args,
                        request,
                        call_object,
                        1,
                        missing_name,
                        dont_publish_class,
                        request,
                        bind=1,
                        )

        if result is not response:
            response.setBody(result)

        notify(pubevents.PubBeforeCommit(request))

        if not repoze_tm_active and transactions_manager:
            transactions_manager.commit()
            notify(pubevents.PubSuccess(request))

    finally:
        endInteraction()

    return response


class _RequestCloserForTransaction(object):
    """Unconditionally close the request at the end of a transaction.

    See transaction.interfaces.ISynchronizer
    """

    def __init__(self):
        self.requests = {}

    def add(self, txn, request):
        assert txn not in self.requests
        self.requests[txn] = request

    def beforeCompletion(self, txn):
        pass

    newTransaction = beforeCompletion

    def afterCompletion(self, txn):
        request = self.requests.pop(txn, None)
        if request is not None:
            if txn.status == 'Committed':
                notify(pubevents.PubSuccess(request))

            request.close()

_request_closer_for_repoze_tm = _RequestCloserForTransaction()


def publish_module(environ, start_response,
                   _publish=publish,                # only for testing
                   _response_factory=WSGIResponse,  # only for testing
                   _request_factory=HTTPRequest,    # only for testing
                   ):
    module_info = get_module_info('Zope2')
    transactions_manager = module_info[7]

    status = 200
    stdout = StringIO()
    stderr = StringIO()
    response = _response_factory(stdout=stdout, stderr=stderr)
    response._http_version = environ['SERVER_PROTOCOL'].split('/')[1]
    response._server_version = environ.get('SERVER_SOFTWARE')

    request = _request_factory(environ['wsgi.input'], environ, response)

    repoze_tm_active = 'repoze.tm.active' in environ

    if repoze_tm_active:
        # NOTE: registerSynch is a no-op after the first request
        transaction.manager.registerSynch(_request_closer_for_repoze_tm)
        txn = transaction.get()
        _request_closer_for_repoze_tm.add(txn, request)

    setDefaultSkin(request)

    try:
        try:
            response = _publish(request, module_info, repoze_tm_active)
        except Exception:
            try:
                exc_info = sys.exc_info()
                notify(pubevents.PubBeforeAbort(
                    request, exc_info, request.supports_retry()))

                if not repoze_tm_active and transactions_manager:
                    transactions_manager.abort()

                notify(pubevents.PubFailure(
                    request, exc_info, request.supports_retry()))
            finally:
                del exc_info
            raise
    except Unauthorized:
        response._unauthorized()
    except Redirect as v:
        response.redirect(v)

    # Start the WSGI server response
    status, headers = response.finalize()
    start_response(status, headers)

    body = response.body

    if isinstance(body, file) or IUnboundStreamIterator.providedBy(body):
        result = body
    else:
        # If somebody used response.write, that data will be in the
        # stdout StringIO, so we put that before the body.
        # XXX This still needs verification that it really works.
        result = (stdout.getvalue(), response.body)

    if not repoze_tm_active:
        request.close()  # this aborts the transaction!

    stdout.close()

    for callable in response.after_list:
        callable()

    # Return the result body iterable.
    return result
