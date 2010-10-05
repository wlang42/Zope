import unittest
import Zope2
Zope2.startup()

import string, random

from time import time

from OFS.SimpleItem import SimpleItem
from DateTime import DateTime
from BTrees.IIBTree import weightedIntersection
from Products.PluginIndexes.FieldIndex.FieldIndex import FieldIndex
from Products.PluginIndexes.KeywordIndex.KeywordIndex import KeywordIndex
from Products.PluginIndexes.CompositeIndex.CompositeIndex import CompositeIndex



states = ['published','pending','private','intranet']
types  = ['Document','News','File','Image']
default_pages = [True,False,False,False,False,False]


class TestObject(object):

    def __init__(self, id, portal_type, review_state,is_default_page=False):
        self.id = id
        self.portal_type = portal_type
        self.review_state = review_state
        self.is_default_page = is_default_page

    def getPhysicalPath(self):
        return ['',self.id,]

    def __repr__(self):
        return "< %s, %s, %s, %s >" % (self.id,self.portal_type,self.review_state,self.is_default_page)
        
class RandomTestObject(TestObject):

    def __init__(self, id):
        
        i = random.randint(0,len(types)-1)
        portal_type = types[i]
        
        i = random.randint(0,len(states)-1)
        review_state = states[i]

        i = random.randint(0,len(default_pages)-1)
        is_default_page = default_pages[i]
        
        super(RandomTestObject,self).__init__(id,portal_type,review_state,is_default_page)


class CompositeIndexTests( unittest.TestCase ):

    def setUp(self):

        self._index = CompositeIndex('comp01',extra = {'indexed_attrs': 'is_default_page,review_state,portal_type'})
        
        self._field_indexes = ( FieldIndex('review_state'), FieldIndex('portal_type'), FieldIndex('is_default_page'))

        

    def _defaultSearch(self, req, expectedValues=None ):
        
        rs = None
        for index in self._field_indexes:
            r = index._apply_index(req)
            if r is not None:
                r, u = r
            w, rs = weightedIntersection(rs, r)
            if not rs:
                break
        return rs

    
    def _compositeSearch(self, req, expectedValues=None):
        query = self._index.make_query(req)
        rs = None
        r =  self._index._apply_index(query)
        if r is not None:
            r, u = r
        w, rs = weightedIntersection(rs, r)
        return rs
    

    def _populateIndexes(self, k , v):
        self._index.index_object( k, v )
        for index in self._field_indexes:
            index.index_object( k, v )


    def _clearIndexes(self):
        self._index.clear()
        for index in self._field_indexes:
            index.clear()

    def testPerformance(self):

        lengths = [10,100,1000,10000,100000]

        queries = [{  'portal_type' : { 'query': 'Document' } , 
                      'review_state' : { 'query': 'pending' } }  ,\
                   {  'is_default_page': { 'query' : True }, 
                      'portal_type' : { 'query': 'Document' } , 
                      'review_state' : { 'query' : 'pending'}}
                   ]        

        def profileSearch(*args, **kw):


            st = time()
            res1 = self._defaultSearch(*args, **kw)
            print list(res1)
            print "atomic:    %s hits in %3.2fms" % (len(res1), (time() -st)*1000)

            st = time()
            res2 = self._compositeSearch(*args, **kw)
            print list(res2)
            print "composite: %s hits in %3.2fms" % (len(res2), (time() -st)*1000)

            self.assertEqual(len(res1),len(res2))

            for i,v in enumerate(res1):
                self.assertEqual(res1[i], res2[i])  



        for l in lengths:
            self._clearIndexes()
            print "************************************" 
            print "indexed objects: %s" % l
            for i  in range(l):
                name = 'dummy%s' % i
                obj = RandomTestObject(name)
                print obj
                self._populateIndexes(i,obj)

            for query in queries:
                print query
                profileSearch(query)


      
        print "************************************"


    def XXXXXXXXXXXXtestSearch(self):

        obj = TestObject('obj1','Document','pending')
        self.cat.catalog_object(obj)
        
        obj = TestObject('obj2','News','pending')
        self.cat.catalog_object(obj)
        
        obj = TestObject('obj3','News','visible')
        self.cat.catalog_object(obj)       
        
        queries = [{ 'review_state': { 'query':'pending'} ,'portal_type' : { 'query': 'Document'} },
                   { 'review_state': { 'query' : ('pending','visible') } , 'portal_type' : { 'query': 'News' }},
                   { 'review_state': { 'query': 'pending' } ,'portal_type' : { 'query': ('News','Document')}},
                   { 'review_state': { 'query': ('pending','visible')} ,'portal_type' : { 'query' : ('News','Document')}}
                   ]

        for query in queries:
        
            res1 = self._defaultSearch(**query)
            res2 = self._compositeSearch(**query)

            self.assertEqual(len(res1),len(res2))

            for i,v in enumerate(res1):
                self.assertEqual(res1[i], res2[i])

def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(CompositeIndexTests),
        ))
      
