# -*- coding: utf-8 -*-
import codecs
import Testing.ZopeTestCase
import Testing.testbrowser
import Zope2.App


class SortingTests(Testing.ZopeTestCase.FunctionalTestCase):
    """Browser testing ..Image.File"""

    def setUp(self):
        super(SortingTests, self).setUp()

        Zope2.App.zcml.load_site(force=True)

        uf = self.app.acl_users
        uf.userFolderAddUser('manager', 'manager_pass', ['Manager'], [])

        self.app.manage_addFolder('sortingTest')
        self.app.manage_addOrderedFolder('sortingTestOrdered')
        for folder in [self.app.sortingTest, self.app.sortingTestOrdered]:
            folder.manage_addFile('File2')
            folder.manage_addFile('File1')
            folder.File1.update_data(u'hällo'.encode('utf-8'))

        self.browser = Testing.testbrowser.Browser()
        self.browser.addHeader(
            'Authorization',
            'basic {}'.format(codecs.encode(
                b'manager:manager_pass', 'base64').decode()))

    def check_order(self, expect_1_before_2):
        found_1_before_2 = (
            self.browser.contents.find('File2') >
            self.browser.contents.find('File1')
        )
        self.assertEqual(found_1_before_2, expect_1_before_2)

    def test_sortby(self):
        base_url = 'http://localhost/sortingTest/manage_main?skey=%s&rkey=%s'

        self.browser.open(base_url % ('id', 'asc'))
        self.check_order(expect_1_before_2=True)

        self.browser.open(base_url % ('id', 'desc'))
        self.check_order(expect_1_before_2=False)

        self.browser.open(base_url % ('get_size', 'asc'))
        self.check_order(expect_1_before_2=False)

        self.browser.open(base_url % ('get_size', 'desc'))
        self.check_order(expect_1_before_2=True)

    def test_sortby_ordered(self):
        base_url = 'http://localhost/sortingTestOrdered/manage_main?'

        self.browser.open(base_url)
        self.check_order(expect_1_before_2=False)

        self.browser.open(base_url + 'rkey=desc')
        self.check_order(expect_1_before_2=True)

        self.browser.open(base_url + 'skey=id&rkey=asc')
        self.check_order(expect_1_before_2=True)

        self.browser.open(base_url + 'skey=id&rkey=desc')
        self.check_order(expect_1_before_2=False)
