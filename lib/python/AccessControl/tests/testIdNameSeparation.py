##############################################################################
#
# Copyright (c) 2001 Zope Corporation and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
"""User folder tests
"""

__rcs_id__='$Id:$'
__version__='$Revision:$'[11:-2]

import os, sys, base64, unittest

from Testing.makerequest import makerequest

import transaction

import Zope2
Zope2.startup()

from AccessControl import Unauthorized
from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.SecurityManagement import noSecurityManager
from AccessControl import getSecurityManager
from AccessControl.User import BasicUserFolder, UserFolder
from AccessControl.User import User


from BTrees.IOBTree import IOBTree
from BTrees.Length import Length

class RenamingUser(User):
    def __init__(self, name, password, roles, domains, userid):
        self.userid = userid
        User.__init__(self, name, password, roles, domains)

    def getId(self):
        return self.userid

class RenamingUserFolder(UserFolder):
    # maps names to userids
    _idMap = None
    _count = None

    def __init__(self, *args, **kw):
        self._idMap = IOBTree()
        self._count = Length()
        UserFolder.__init__(self, *args, **kw)

    def _doAddUser(self, name, password, roles, domains, **kw):
        """Create a new user"""
        if password is not None and self.encrypt_passwords:
            password = self._encryptPassword(password)
        
        count = self._count()
        userid=str(count)
        self._idMap[count] = self.data[name] = RenamingUser(name,password,roles,domains,userid)
        self._count.change(1)

    def getUserById(self, userid, default=None):
        try:
            count = int(userid)
        except ValueError:
            # not an int
            return default
        try:
            user = self._idMap.get(count, default)
        except TypeError:
            # count is a Long?
            return default
        return user

        user = self.getUser(name)
        if user is None:
            return default
        return user

    def renameUser(self, oldname, newname):
        u = self.getUser(oldname)
        u.name = newname
        del self.data[oldname]
        self.data[newname] = u

    def _doDelUsers(self, names):
        for name in names:
            count = int(self.data[name].getId())
            del self.data[name]
            del self._idMap[count]

class BaseTestCase(unittest.TestCase):

    def setUp(self):
        transaction.begin()
        self.app = makerequest(Zope2.app())
        try:
            # Set up a user and role
            self.app._delObject('acl_users')
            self.app._setObject('acl_users', RenamingUserFolder())
            self.uf = self.app.acl_users
            self.uf._doAddUser('user1', 'secret', ['role1'], [])
            self.app._addRole('role1')
            self.app.manage_role('role1', ['View'])
            # Set up a published object accessible to user
            self.app.addDTMLMethod('doc', file='')
            self.app.doc.manage_permission('View', ['role1'], acquire=0)
            # Rig the REQUEST so it looks like we traversed to doc
            self.app.REQUEST.set('PUBLISHED', self.app.doc)
            self.app.REQUEST.set('PARENTS', [self.app])
            self.app.REQUEST.steps = ['doc']
            self.basic = 'Basic %s' % base64.encodestring('user1:secret')
        except:
            self.tearDown()
            raise

    def tearDown(self):
        noSecurityManager()
        transaction.abort()
        self.app._p_jar.close()

    def login(self, name):
        user = self.uf.getUser(name)
        user = user.__of__(self.uf)
        newSecurityManager(None, user)


class HarnessTests(BaseTestCase):
    # Tests to check our custom classes are working

    def testAddUser(self):
        # a user was already added by BaseTestCase, check status
        self.assertEquals(self.uf._count(), 1)
        u1 = self.uf.getUser('user1')
        self.failUnless(isinstance(u1, RenamingUser))
        self.assertEquals(id(u1), id(self.uf.getUserById('0')),
                          "getUser('user1') does not match getUserById('0')")
        self.assertEquals(u1.getId(), '0')
        self.assertEquals(u1.getUserName(), 'user1')
        marker = object()
        self.assertEquals(self.uf.getUserById('1', marker), marker)

        # now try adding another user to check behaviour
        self.uf._doAddUser('user2', 'secret', ['role1'], [])
        self.assertEquals(self.uf._count(), 2)
        u1 = self.uf.getUser('user1') # get it again, just in case...
        u2 = self.uf.getUser('user2')
        self.failIfEqual(u1, u2)
        self.failUnless(isinstance(u2, RenamingUser))
        self.assertEquals(id(u2), id(self.uf.getUserById('1')),
                          "getUser('user2') does not match getUserById('1')")
        self.assertEquals(u2.getId(), '1')
        self.assertEquals(u2.getUserName(), 'user2')
       
    def testRenameUser(self):
        marker = object()
        u1 = self.uf.getUser('user1')
        u1id = u1.getId()
        
        self.uf.renameUser('user1', 'user2')

        u2 = self.uf.getUser('user2')
        self.assertEquals(id(u1), id(u2))
        self.assertEquals(id(u2), id(self.uf.getUserById(u1id)))
        self.assertEquals(u1id, u2.getId())
        self.assertEquals(u1.getUserName(), 'user2')
        self.assertEquals(self.uf.getUser('user1'), None)
        self.assertEquals(self.uf.getUserById('1', marker), marker)

    def testDelUser(self):
        self.uf._doDelUsers(['user1'])
        self.assertEquals(len(self.uf._idMap), 0)
        self.assertEquals(len(self.uf.data), 0)
        
    def testGetRoles(self):
        user = self.uf.getUser('user1')
        self.failUnless('role1' in user.getRoles())

        self.uf.renameUser('user1', 'user2')
        self.uf._doAddUser('user1', 'secret', ['role0'], [])
        self.failUnless('role1' in user.getRoles())
        self.failIf('role0' in user.getRoles())

        # try getting the user again w/ the new name, just in case
        user = self.uf.getUser('user2')
        self.failUnless('role1' in user.getRoles())
        self.failIf('role0' in user.getRoles())

        # now get the new user w/ the old name and check the roles
        user = self.uf.getUser('user1')
        self.failIf('role1' in user.getRoles())
        self.failUnless('role0' in user.getRoles())

class LocalRolesTests(BaseTestCase):

    def testGetRolesInContext(self):
        user = self.uf.getUser('user1')
        self.app.manage_addLocalRoles('user1', ['Owner'])
        roles = user.getRolesInContext(self.app)
        self.failUnless('role1' in roles, "no 'role1' in roles")
        self.failUnless('Owner' in roles, "no 'Owner' in roles")
        
        self.uf.renameUser('user1', 'user2')
        user = self.uf.getUser('user2')
        roles = user.getRolesInContext(self.app)
        self.failUnless('role1' in roles)
        self.failUnless('Owner' in roles)

    def testGetRolesInContext2(self):
        self.app.manage_addLocalRoles('user1', ['Owner'])
        self.uf.renameUser('user1', 'user2')
        self.app._addRole('role0')

        self.uf._doAddUser('user1', 'secret', ['role0'], [])
        user = self.uf.getUser('user1')
        roles = user.getRolesInContext(self.app)
        self.failIf('role2' in roles)
        self.failIf('role2' in roles)
        self.failIf('Owner' in roles)

    def testWrapMissingUserId(self):
        from AccessControl.Role import _wrapMissingUserId, _unwrapMissingUserId
        uid = 'with space and null(\x00) and 8bit (\xe7)'
        expected = '_MISSING_with+space+and+null%28%00%29+and+8bit+%28%E7%29'
        self.assertEquals(_wrapMissingUserId(uid), expected)
        self.assertEquals(_unwrapMissingUserId(_wrapMissingUserId(uid)), uid)
        self.assertEquals(_unwrapMissingUserId('regularUserName'), None)

    def test_get_local_roles(self):
        self.app.manage_addLocalRoles('user1', ['Owner'])
        self.assertEquals(self.app.get_local_roles(),
                          (('user1', ('Owner',)),) )
        self.uf.renameUser('user1', 'user2')
        self.assertEquals(self.app.get_local_roles(),
                          (('user2', ('Owner',)),) )

    def test_get_local_roles_for_userid(self):
        # test the misnamed method actually works for usernames
        # as usernames are what this method will get from the ZMI
        self.app.manage_addLocalRoles('user1', ['Owner'])
        self.assertEquals(self.app.get_local_roles_for_userid('user1'),
                          ('Owner',))
        self.uf.renameUser('user1', 'user2')
        self.assertEquals(self.app.get_local_roles_for_userid('user1'),
                          ())
        self.assertEquals(self.app.get_local_roles_for_userid('user2'),
                          ('Owner',))

    def testMissingUserIdSupport(self):
        self.app.manage_addLocalRoles('user1', ['Owner'])
        self.assertEquals(self.app.get_local_roles(),
                          (('user1', ('Owner',)),) )
        self.uf._doDelUsers(['user1'])
        self.assertEquals(self.app.get_local_roles(),
                          (('_MISSING_0', ('Owner',)),))

    def testHasLocalRole(self):
        self.app.manage_addLocalRoles('user1', ['Owner'])
        user = self.uf.getUser('user1')
        self.failUnless(user.has_role('Owner', self.app))

        self.uf.renameUser('user1', 'user2')
        user = self.uf.getUser('user2')
        self.failUnless(user.has_role('Owner', self.app))

        self.uf._doAddUser('user1', 'secret', [], [])
        user = self.uf.getUser('user1')
        self.failIf(user.has_role('Owner', self.app))

    def testHasLocalRolePermission(self):
        self.app.manage_role('Owner', ['Add Folders'])
        self.app.manage_addLocalRoles('user1', ['Owner'])
        user = self.uf.getUser('user1')
        self.failUnless(user.has_permission('Add Folders', self.app))
        
        self.uf.renameUser('user1', 'user2')
        self.uf._doAddUser('user1', 'secret', [], [])

        user = self.uf.getUser('user1')
        self.failIf(user.has_permission('Add Folders', self.app))

        user = self.uf.getUser('user2')
        self.failUnless(user.has_permission('Add Folders', self.app))

    def test_security_checkPermission(self):
        self.app.manage_role('Owner', ['Add Folders'])
        self.app.manage_addLocalRoles('user1', ['Owner'])
        self.login('user1')
        security = getSecurityManager()
        self.failUnless(security.checkPermission('Add Folders', self.app),
                        'disallowed before rename')
        noSecurityManager()

        self.uf.renameUser('user1', 'user2')
        self.login('user2')
        security = getSecurityManager()
        self.failUnless(security.checkPermission('Add Folders', self.app),
                        'disallowed after rename')

        noSecurityManager()
        self.uf._doAddUser('user1', 'secret', [], [])
        self.login('user1')
        security = getSecurityManager()
        self.failIf(security.checkPermission('Add Folders', self.app),
                    'allowed user with old name')

    def test_acl_users_generator(self):
        self.app.manage_addFolder('aFolder')
        self.app.aFolder.manage_addUserFolder()
        ufpaths = ['/'.join(uf.getPhysicalPath())
                   for uf in self.app.aFolder._acl_users_generator()]
        self.assertEquals(ufpaths, ['/aFolder/acl_users',
                                    '/acl_users'])

class OwnershipTests(BaseTestCase):

    def setUp(self):
        BaseTestCase.setUp(self)

    def test_manage_owner(self):
        self.login('user1')
        user = self.uf.getUser('user1')
        self.app.manage_addFolder('aFolder')
        self.app.REQUEST.traverse("/aFolder")
        r = self.app.aFolder.manage_owner(REQUEST=self.app.REQUEST)
        self.failUnless('owned by user1 (acl_users).' in r,
                        r)

    def test_onwer_info(self):
        self.login('user1')
        user = self.uf.getUser('user1')
        self.app.manage_addFolder('aFolder')

        self.assertEquals(self.app.aFolder.owner_info(),
                          {'path': 'acl_users',
                           'explicit': True,
                           'id': '0',
                           'name': 'user1',
                           'userCanChangeOwnershipType': 1})

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(HarnessTests))
    suite.addTest(unittest.makeSuite(LocalRolesTests))
    suite.addTest(unittest.makeSuite(OwnershipTests))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
