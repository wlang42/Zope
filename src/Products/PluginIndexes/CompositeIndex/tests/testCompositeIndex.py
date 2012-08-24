import unittest
import Zope2
#Zope2.startup()

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
keywords = map(lambda x: 'subject_%s' % x,range(1,6))

class TestObject(object):

    def __init__(self, id, portal_type, review_state,is_default_page=False,subject= []):
        self.id = id
        self.portal_type = portal_type
        self.review_state = review_state
        self.is_default_page = is_default_page
        self.subject=subject

    def getPhysicalPath(self):
        return ['',self.id,]

    def __repr__(self):
        return "< %s, %s, %s, %s, %s >" % (self.id,self.portal_type,self.review_state,self.is_default_page,subject)
        
class RandomTestObject(TestObject):

    def __init__(self, id):
        
        i = random.randint(0,len(types)-1)
        portal_type = types[i]
        
        i = random.randint(0,len(states)-1)
        review_state = states[i]

        i = random.randint(0,len(default_pages)-1)
        is_default_page = default_pages[i]
        
        #subject = random.sample(keywords,random.randint(1,int(len(keywords)*0.2)))
        subject = random.sample(keywords,random.randint(1,len(keywords)))

        super(RandomTestObject,self).__init__(id,portal_type,review_state,is_default_page,subject)


class CompositeIndexTests( unittest.TestCase ):

    def setUp(self):

        self._index = CompositeIndex('comp01',
                                     extra = [ { 'id': 'is_default_page' ,'meta_type': 'FieldIndex','attributes':''},
                                               { 'id': 'review_state' ,'meta_type': 'FieldIndex','attributes':''},
                                               { 'id': 'portal_type' ,'meta_type': 'FieldIndex','attributes':''},
                                               {'id': 'subject' ,'meta_type': 'KeywordIndex','attributes':''}         
])
        
        self._field_indexes = ( FieldIndex('review_state'), FieldIndex('portal_type'), FieldIndex('is_default_page'),KeywordIndex('subject'))

        

    def _defaultSearch(self, req, expectedValues=None ):
        
        rs = None
        for index in self._field_indexes:
            r = index._apply_index(req)
            if r is not None:
                r, u = r
                w, rs = weightedIntersection(rs, r)
                if not rs:
                    break
        if not rs:
            return set()
        return set(rs)

    
    def _compositeSearch(self, req, expectedValues=None):
        
        query = self._index.make_query(req)
        rs = None
        r =  self._index._apply_index(query)
        if r is not None:
            r, u = r
            w, rs = weightedIntersection(rs, r)
        if not rs:
            return set()
        return set(rs)
    

    def _populateIndexes(self, k , v):
        self._index.index_object( k, v )
        for index in self._field_indexes:
            index.index_object( k, v )



    def _clearIndexes(self):
        self._index.clear()
        for index in self._field_indexes:
            index.clear()

    def testPerformance(self):

        lengths = [1000,10000,100000]

        queries = [{  'portal_type' : { 'query': 'Document' }} ,
                   {  'portal_type' : { 'query': 'Document' } , 
                      'review_state' : { 'query': 'pending' }}  ,\
                   {  'is_default_page': { 'query' : False }, 
                      'portal_type' : { 'query': 'Document' } , 
                      'review_state' : { 'query' : 'pending'}},
                   {  'is_default_page': { 'query' : False },
                      'portal_type' : { 'query': 'Document' } ,
                      'review_state' : { 'query' : 'private'},
                      'subject': { 'query' : ['subject_2','subject_3'] ,'operator': 'or' }},
                   ]

        def profileSearch(*args, **kw):


            st = time()
            res1 = self._defaultSearch(*args, **kw)
            print "atomic:    %s hits in %3.2fms" % (len(res1), (time() -st)*1000)

            st = time()
            res2 = self._compositeSearch(*args, **kw)
            print "composite: %s hits in %3.2fms" % (len(res2), (time() -st)*1000)
            

            self.assertEqual(len(res1),len(res2))
            
            self.assertEqual(res1,res2)




        for l in lengths:
            self._clearIndexes()
            print "************************************" 
            print "indexed objects: %s" % l
            for i  in range(l):
                name = '%s' % i
                obj = RandomTestObject(name)
                self._populateIndexes(i,obj)

            for query in queries:
                profileSearch(query)


      
        print "************************************"


    def xxxx_testSearch(self):

        obj = TestObject('obj1','Document','pending')
        self._populateIndexes(1 , obj)
        
        
        obj = TestObject('obj2','News','pending')
        self._populateIndexes(2 , obj)
        
        
        obj = TestObject('obj3','News','visible')
        self._populateIndexes(3 , obj)
        
        queries = [{ 'review_state': { 'query':'pending'} ,'portal_type' : { 'query': 'Document'} },
                   { 'review_state': { 'query' : ('pending','visible') } , 'portal_type' : { 'query': 'News' }},
                   { 'review_state': { 'query': 'pending' } ,'portal_type' : { 'query': ('News','Document')}},
                   { 'review_state': { 'query': ('pending','visible')} ,'portal_type' : { 'query' : ('News','Document')}}
                   ]

        for query in queries:
        
            res1 = self._defaultSearch(query)
            res2 = self._compositeSearch(query)

            self.assertEqual(len(res1),len(res2))

            for i,v in enumerate(res1):
                self.assertEqual(res1[i], res2[i])

def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(CompositeIndexTests),
        ))
      
