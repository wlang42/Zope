##############################################################################
#
# Copyright (c) 2010 Zope Foundation and Contributors.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################

import sys
import logging

from Acquisition import aq_parent

from Globals import DTMLFile

from time import time

from BTrees.IIBTree import IIBTree, IITreeSet, IISet, union, intersection, difference
from BTrees.OOBTree import OOBTree
from BTrees.IOBTree import IOBTree
import BTrees.Length

from ZODB.POSException import ConflictError

from Products.PluginIndexes.interfaces import IUniqueValueIndex
from Products.PluginIndexes.KeywordIndex.KeywordIndex import KeywordIndex
from Products.PluginIndexes.common.util import parseIndexRequest

from util import PermuteKeywordList

from config import PROJECTNAME

_marker = []

logger = logging.getLogger(PROJECTNAME)

class CompositeIndex(KeywordIndex):

    """Index for composition of simple fields.
       or sequences of items
    """


    meta_type="CompositeIndex"

    manage_options= (
        {'label': 'Settings',
         'action': 'manage_main',
         'help': ('CompositeIndex','CompositeIndex_Settings.stx')},
        {'label': 'Browse',
         'action': 'manage_browse',
         'help': ('CompositeIndex','CompositeIndex_Settings.stx')},
    )

    def clear(self):
        self._length = BTrees.Length.Length()
        self._index = IOBTree()
        self._unindex = IOBTree()

        # translation from hash key to human readable composite key
        self._tindex = IOBTree()

        # component indexes
        self._cindexes = OOBTree()
        for i in self.getComponentIndexNames():
            self._cindexes[i] = OOBTree()
        

    def _apply_index(self, request, cid='', type=type):
        """ Apply the index to query parameters given in the request arg. """
        
        record = parseIndexRequest(request, self.id, self.query_options)
        if record.keys==None: return None

        if len(record.keys) > 0 and not isinstance(record.keys[0][1],parseIndexRequest):
            if isinstance(record.keys[0],tuple):
                for i,k in enumerate(record.keys):
                    record.keys[i] = hash(k)
                    
            return super(CompositeIndex,self)._apply_index(request, cid=cid, type=type)
         
        operator = self.useOperator

        rank=[]
        
        for c, rec in record.keys:
            # experimental code for specifing the operator
            if operator == self.useOperator:
                operator = rec.get('operator',operator)
                
            if not operator in self.operators :
                raise RuntimeError,"operator not valid: %s" % escape(operator)

            res = self._apply_component_index(rec,c)

            if res is None:
                continue
                
            res, dummy  = res 

            rank.append((len(res),res))


        # sort from short to long sets
        rank.sort()

        k     = None
        for l,res in rank:

            k = intersection(k, res)

            if not k:
                break


        # if any operator of composite indexes is set to "and"
        # switch to intersecton mode
        
        if operator == 'or':
            set_func = union
        else:
            set_func = intersection

        
        rank=[]
        if set_func == intersection:
            for key in k:
                set=self._index.get(key, IISet())
                rank.append((len(set),key))
        
            # sort from short to long sets
            rank.sort()

        else:
            # dummy length
            if k:
                rank = enumerate(k)

        res = None
        # collect docIds

        for l,key in rank:
            
            set=self._index.get(key, None)
            if set is None:
                set = IISet(())
            elif isinstance(set, int):
                set = IISet((set,))
            res = set_func(res, set)
            if not res and set_func is intersection:
                break


        if isinstance(res, int):  r=IISet((res,))

        if res is None:
            return IISet(),(self.id,)

        return res, (self.id,)
        

    def _apply_component_index(self, record, cid):
        """ Apply the component index to query parameters given in the record arg. """
        
        if record.keys==None: return None

        index = self._cindexes[cid]
        r     = None
        opr   = None

 
        # Range parameter
        range_parm = record.get('range',None)
        if range_parm:
            opr = "range"
            opr_args = []
            if range_parm.find("min")>-1:
                opr_args.append("min")
            if range_parm.find("max")>-1:
                opr_args.append("max")

        if record.get('usage',None):
            # see if any usage params are sent to field
            opr = record.usage.lower().split(':')
            opr, opr_args=opr[0], opr[1:]

        if opr=="range":   # range search
            if 'min' in opr_args: lo = min(record.keys)
            else: lo = None
            if 'max' in opr_args: hi = max(record.keys)
            else: hi = None
            if hi:
                setlist = index.items(lo,hi)
            else:
                setlist = index.items(lo)

            for k, set in setlist:
                if isinstance(set, tuple):
                    set = IISet((set,))
                r = union(r, set)
        else: # not a range search
            for key in record.keys:
                set=index.get(key, None)
                if set is None:
                    set = IISet(())
                elif isinstance(set, int):
                    set = IISet((set,))
                r = union(r, set)

        if isinstance(r, int):
            r=IISet((r,))

        if r is None:
            return IISet(), (cid,)
        
        return r, (cid,)
            


    def index_object(self, documentId, obj, threshold=None):
        """ wrapper to handle indexing of multiple attributes """

        res = self._index_object(documentId, obj, threshold)

        return res


    def _index_object(self, documentId, obj, threshold=None, attr=''):
        """ index an object 'obj' with integer id 'i'

        Ideally, we've been passed a sequence of some sort that we
        can iterate over. If however, we haven't, we should do something
        useful with the results. In the case of a string, this means
        indexing the entire string as a keyword."""

        # First we need to see if there's anything interesting to look at
        # self.id is the name of the index, which is also the name of the
        # attribute we're interested in.  If the attribute is callable,
        # we'll do so.

        # unhashed keywords
        newUKeywords = self._get_object_keywords(obj, attr)

        
        # hashed keywords
        newKeywords = map(lambda x: hash(x),newUKeywords)
        
        for i, kw in enumerate(newKeywords):
            if not self._tindex.get(kw,None):
                self._tindex[kw]=newUKeywords[i]


            
        newKeywords = map(lambda x: hash(x),newUKeywords)

        oldKeywords = self._unindex.get(documentId, None)

        if oldKeywords is None:
            # we've got a new document, let's not futz around.
            try:
                for kw in newKeywords:
                    self.insertForwardIndexEntry(kw, documentId)
                self._unindex[documentId] = list(newKeywords)
            except TypeError:
                return 0
        else:
            # we have an existing entry for this document, and we need
            # to figure out if any of the keywords have actually changed
            if type(oldKeywords) is not IISet:
                oldKeywords = IISet(oldKeywords)
            newKeywords = IISet(newKeywords)
            fdiff = difference(oldKeywords, newKeywords)
            rdiff = difference(newKeywords, oldKeywords)
            if fdiff or rdiff:
                # if we've got forward or reverse changes
                self._unindex[documentId] = list(newKeywords)
                if fdiff:
                    self.unindex_objectKeywords(documentId, fdiff)

                    for kw in fdiff:
                        indexRow = self._index.get(kw, _marker)
                        try:
                            del self._tindex[kw]
                        except KeyError:
                            # XXX should not happen
                            pass
                        
                if rdiff:
                    for kw in rdiff:
                        self.insertForwardIndexEntry(kw, documentId)

        return 1


    def insertForwardIndexEntry(self, entry, documentId):
        """Take the entry provided and put it in the correct place
        in the forward index.

        This will also deal with creating the entire row if necessary.
        """
        super(CompositeIndex,self).insertForwardIndexEntry(entry, documentId)
        self._insertComponentIndexEntry(entry)
        

    def removeForwardIndexEntry(self, entry, documentId):
        """Take the entry provided and remove any reference to documentId
           in its entry in the index.
        """
        super(CompositeIndex,self).removeForwardIndexEntry(entry, documentId)
        self._removeComponentIndexEntry(entry)
        

    def _insertComponentIndexEntry(self, entry):
        """Take the entry provided, extract its components and
           put it in the correct place of the component index.
           entry - hashed composite key """

        # get the composite key and extract its component values
        components = self._tindex[entry]

        for i,c in enumerate(self.getComponentIndexNames()):
            ci = self._cindexes[c]
            cd = components[i]

            indexRow = ci.get(cd, _marker)
            if indexRow is _marker:
                ci[cd] = entry

            else:
                try:
                    indexRow.insert(entry)
                except AttributeError:
                    # index row is not a IITreeSet
                    indexRow = IITreeSet((indexRow, entry))
                    ci[cd] = indexRow

    
    def _removeComponentIndexEntry(self, entry):
        """ Take the entry provided, extract its components and
            remove any reference to composite key of each component index.
            entry - hashed composite key"""

        # get the composite key and extract its component values
        components = self._tindex[entry]

        for i,c in enumerate(self.getComponentIndexNames()):
            ci = self._cindexes[c]
            cd = components[i]
            indexRow = ci.get(cd, _marker)
            if indexRow is not _marker:
                try:
                    indexRow.remove(entry)
                    if not indexRow:
                        del ci[cd]
                except ConflictError:
                    raise           

                except AttributeError:
                    # index row is an int
                    try:
                        del ci[cd]
                    except KeyError:
                        pass
                
                except:
                    logger.error('%s: unindex_object could not remove '
                                 'entry %s from component index %s[%s].  This '
                                 'should not happen.' % (self.__class__.__name__,
                                                         str(components),str(self.id),str(c)),
                                 exc_info=sys.exc_info())

            else:
                logger.error('%s: unindex_object tried to retrieve set %s '
                             'from component index %s[%s] but couldn\'t.  This '
                             'should not happen.' % (self.__class__.__name__,
                                                    repr(components),str(self.id),str(c)))
        
    def _get_object_keywords(self, obj, attr):
        """ composite keyword lists """    

        fields = self.getComponentIndexAttributes()
         
        kw_list = []

        for attributes in fields:
            kw = []
            for attr in attributes:
                kw.extend(list(super(CompositeIndex,self)._get_object_keywords(obj, attr)))
            kw_list.append(kw)
        
        pkl = PermuteKeywordList(kw_list)

        return pkl.keys

    def getComponentIndexNames(self):
        """ returns component index names to composite """

        ids = []

        fields = self.getIndexSourceNames()
        for attr in fields:
            c = attr.split(':')
            ids.append(c.pop())

        return tuple(ids)

    def getComponentIndexAttributes(self):
        """ returns list of attributes of each component index to composite"""

        attributes=[]
        
        fields = self.getIndexSourceNames()
        for idx in fields:
            attr =  idx.split(':')
            if len(attr) == 1:
                attributes.append(attr) 
            else:
                attributes.append(attr[1:])

        return tuple(attributes)

    def getEntryForObject(self, documentId, default=_marker):
        """Takes a document ID and returns all the information we have
        on that specific object.
        """
        datum = super(CompositeIndex,self).getEntryForObject(documentId, default=default)

        if isinstance(datum, int):
            datum = IISet((datum,))

        entry = map(lambda k : self._tindex.get(k,k), datum)   

        return entry

    def keyForDocument(self, id):
        # This method is superceded by documentToKeyMap
        logger.warn('keyForDocument: return hashed key')
        return super(CompositeIndex,self).keyForDocument(id)
    
    def documentToKeyMap(self):
        logger.warn('documentToKeyMap: return hashed key map')
        return self._unindex

    def items(self):
        items = []
        for k,v in self._index.items():
            if isinstance(v, int):
                v = IISet((v,))

            kw = self._tindex.get(k,k)
            items.append((kw, v))
        return items
    

    manage = manage_main = DTMLFile('dtml/manageCompositeIndex', globals())
    manage_main._setName('manage_main')
    manage_browse = DTMLFile('dtml/browseIndex', globals())


manage_addCompositeIndexForm = DTMLFile('dtml/addCompositeIndex', globals())

def manage_addCompositeIndex(self, id, extra=None,
                REQUEST=None, RESPONSE=None, URL3=None):
    """Add a composite index"""
    return self.manage_addIndex(id, 'CompositeIndex', extra=extra, \
             REQUEST=REQUEST, RESPONSE=RESPONSE, URL1=URL3)



class compositeSearchArgumentsMap:
    """ parse a request from the ZPublisher to optimize the query by means
        of CompositeIndexes
    """

    keywords = {}
    
    def __init__(self, catalog, request):
        """ indexes -- dict of index objects
            request -- the request dictionary send from the ZPublisher
        """
        
        indexes = catalog.indexes

        parent = aq_parent(catalog)

        if parent.hasProperty('unimr.compositeindex') and not parent.getProperty('unimr.compositeindex',True):
            logger.warn('skip compositeSearchArgumentsMap')
            return
        
        cRank=[]
        for index in indexes.values():
            if isinstance(index,CompositeIndex):
                
                cId = index.id
                logger.debug('CompositeIndex "%s" found' % cId)
                # get indexes managed by CompositeIndex
                cIdxs = index.getComponentIndexNames()
                cRank.append((cId,cIdxs))
        
        # sort from specific to unspecific CompositeIndex
        cRank.sort(lambda x,y: cmp((len(y[1]),y[1]),(len(x[1]),x[1])))

        for cId, cIdxs in cRank:
                records=[]
                for i in cIdxs:
                    index = indexes.get(i,None)
                    abort = False
                    
                    if index:
                        rec = parseIndexRequest(request, index.id, index.query_options)
                        
                        if not IUniqueValueIndex.providedBy(index):
                            logger.warn('index %s: not an instance of IUniqueValueIndex' % index.id)
                            abort = True

                        if abort or rec.keys is None:
                            continue
                        
                        records.append((i, rec))

                        
                # transform request only if more than one component of the composite key is applied 
                if len(records) > 1:

                    query = { cId: { 'query': records } }

                    logger.debug('composite query build "%s"' % query)

                    
                    # delete obsolete query attributes from request
                    for i in cIdxs[:len(records)+1]:
                        
                        if isinstance(request, dict):
                            if request.has_key(i):
                                del request[i]
                        else:
                            if request.keywords.has_key(i):
                                del request.keywords[i]
                            if isinstance(request.request, dict) and \
                                   request.request.has_key(i):
                               
                                del request.request[i]

                    request.keywords.update(query)        
 


