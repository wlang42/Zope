##############################################################################
#
# Copyright (c) 2006 Zope Foundation and Contributors.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Unit tests of makequest.
"""

import unittest

from Acquisition import Implicit
from Testing.makerequest import makerequest
from OFS.Application import Application
from zope.globalrequest import getRequest, clearRequest

class MakerequestTests(unittest.TestCase):

    def tearDown(self):
        clearRequest()

    def test_makerequest(self):
        # The argument must support acquisition.
        #self.assertRaises(AttributeError, makerequest, object())
        # After the call, it will have a REQUEST attribute.
        app = Application()
        self.assertFalse(hasattr(app, 'REQUEST'))
        app = makerequest(app)
        self.failUnless(getRequest() is not None)
        self.assertTrue(hasattr(app, 'REQUEST'))
    
    def test_dont_break_getPhysicalPath(self):
        # see http://www.zope.org/Collectors/Zope/2057.  If you want
        # to call getPhysicalPath() on the wrapped object, be sure
        # that it provides a non-recursive getPhysicalPath().
        class FakeRoot(Application):
            def getPhysicalPath(self):
                return ('foo',)
        item = FakeRoot()
        self.assertEqual(item.getPhysicalPath(),
                         makerequest(item).getPhysicalPath())

    def test_stdout(self):
        # You can pass a stdout arg and it's used by the response.
        import cStringIO
        out = cStringIO.StringIO()
        app = makerequest(Application(), stdout=out)
        app.REQUEST.RESPONSE.write('aaa')
        out.seek(0)
        written = out.read()
        self.assertTrue(written.startswith('Status: 200 OK\r\n'))
        self.assertTrue(written.endswith('\naaa'))

    def test_environ(self):
        # You can pass an environ argument to use in the request.
        environ = {'foofoo': 'barbar'}
        app = makerequest(Application(), environ=environ)
        self.assertEqual(app.REQUEST.environ['foofoo'], 'barbar')

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(MakerequestTests))
    return suite
