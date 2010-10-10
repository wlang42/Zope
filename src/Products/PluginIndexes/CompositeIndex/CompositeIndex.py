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
from Persistence import PersistentMapping


from App.special_dtml import DTMLFile

from BTrees.IIBTree import IIBTree, IITreeSet, IISet, union, intersection, difference
from BTrees.OOBTree import OOBTree
from BTrees.IOBTree import IOBTree
from BTrees.Length import Length


from zope.interface import implements

from ZODB.POSException import ConflictError

from Products.PluginIndexes.interfaces import ITransposeQuery
from Products.PluginIndexes.interfaces import IUniqueValueIndex
from Products.PluginIndexes.common.UnIndex import UnIndex
from Products.PluginIndexes.common.util import parseIndexRequest
from Products.PluginIndexes.common import safe_callable

from util import PermuteKeywordList

QUERY_OPTIONS = { 'FieldIndex' :  ["query","range"] ,
                  'KeywordIndex' : ["query","operator","range"] }

_marker = []

logger = logging.getLogger('CompositeIndex')


class Component:

    def __init__(self,id,type,attributes):
        
        self._id = id
        self._type = type
        
        if isinstance(attributes, str):
            self._attributes = attributes.split(',')
        else:
            self._attributes = list(attributes)
            
        self._attributes = [ attr.strip() for attr in self._attributes if attr ]
        

    @property
    def id(self):
        return self._id

    @property
    def type(self):
        return self._type

    @property
    def attributes(self):
        if not self._attributes:
            return [self._id]
        return self._attributes



class CompositeIndex(UnIndex):

    """Index for composition of simple fields.
       or sequences of items
    """
    
    implements(ITransposeQuery)

    meta_type="CompositeIndex"

    manage_options= (
        {'label': 'Settings',
         'action': 'manage_main',
         'help': ('CompositeIndex','CompositeIndex_Settings.stx')},
        {'label': 'Browse',
         'action': 'manage_browse',
         'help': ('CompositeIndex','CompositeIndex_Settings.stx')},
    )

    query_options = ("query","operator", "range")

    def __init__(
        self, id, ignore_ex=None, call_methods=None, extra=None, caller=None):
        """Create an unindex

        UnIndexes are indexes that contain two index components, the
        forward index (like plain index objects) and an inverted
        index.  The inverted index is so that objects can be unindexed
        even when the old value of the object is not known.

        e.g.

        self._index = {datum:[documentId1, documentId2]}
        self._unindex = {documentId:datum}

        If any item in self._index has a length-one value, the value is an
        integer, and not a set.  There are special cases in the code to deal
        with this.

        The arguments are:

          'id' -- the name of the item attribute to index.  This is
          either an attribute name or a record key.

          'ignore_ex' -- should be set to true if you want the index
          to ignore exceptions raised while indexing instead of
          propagating them.

          'call_methods' -- should be set to true if you want the index
          to call the attribute 'id' (note: 'id' should be callable!)
          You will also need to pass in an object in the index and
          uninded methods for this to work.

          'extra' -- a mapping object that keeps additional
          index-related parameters - subitem 'indexed_attrs'
          can be list of dicts with following keys { id, type, attributes }

          'caller' -- reference to the calling object (usually
          a (Z)Catalog instance
        """

        def _get(o, k, default):
            """ return a value for a given key of a dict/record 'o' """
            if isinstance(o, dict):
                return o.get(k, default)
            else:
                return getattr(o, k, default)

        self.id = id
        self.ignore_ex=ignore_ex        # currently unimplimented
        self.call_methods=call_methods

        self.operators = ('or', 'and')
        self.useOperator = 'or'

        # set components
        self._components = PersistentMapping()
        for cdata in extra:
            c_id = cdata['id']
            c_type = cdata['type']
            c_attributes = cdata['attributes']  
            self._components[c_id] = Component(c_id,c_type,c_attributes)

        if not self._components:
            self._components[id] = Component(id,'KeywordIndex',None)
        
        self._length = Length()
        self.clear()



    def clear(self):
        self._length = Length()
        self._index = IOBTree()
        self._unindex = IOBTree()

        # translation from hash key to human readable composite key
        self._tindex = IOBTree()

        # component indexes
        self._cindexes = OOBTree()
        for i in self.getComponentIndexNames():
            self._cindexes[i] = OOBTree()
        

    def _apply_index(self, request, resultset=None):
        """ Apply the index to query parameters given in the request arg. """
        
        record = parseIndexRequest(request, self.id, self.query_options)
        if record.keys==None: return None

        if len(record.keys) > 0 and not isinstance(record.keys[0][1],parseIndexRequest):
            if isinstance(record.keys[0],tuple):
                for i,k in enumerate(record.keys):
                    record.keys[i] = hash(k)
                    
            return super(CompositeIndex,self)._apply_index(request, resultset=resultset)
         
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

        k = None
        
        for l,res in rank:

            k = intersection(k, res)
            
            if not k:
                break

        # if any operator of composite indexes is set to "and"
        # switch to intersecton mode
        
        if operator == 'or':
            res = None
            set_func = union
        else:
            res = resultset
            set_func = intersection

        
        
        rank=[]
        if set_func == intersection:
            for key in k:
                
                s=self._index.get(key, IISet())
                if isinstance(s, int):
                    rank.append((1,key))
                else:
                    rank.append((len(s),key))
        
            # sort from short to long sets
            rank.sort()
            
        else:
            # dummy length
            if k:
                rank = enumerate(k)

        # collect docIds
        for l,key in rank:
            
            s=self._index.get(key, None)
            if s is None:
                s = IISet(())
            elif isinstance(s, int):
                s = IISet((s,))
            res = set_func(res, s)
            if not res and set_func is intersection:
                break


        if isinstance(res, int):  res = IISet((res,))

        if res is None:
            res = IISet(),(self.id,)

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

            for k, s in setlist:
                if isinstance(s, tuple):
                    s = IISet((s,))
                r = union(r, set)
        else: # not a range search
            for key in record.keys:
                s=index.get(key, None)

                if s is None:
                    s = IISet(())
                elif isinstance(s, int):
                    s = IISet((s,))
                r = union(r, s)

        if isinstance(r, int):
            r=IISet((r,))

        if r is None:
            return IISet(), (cid,)
        
        return r, (cid,)
            


    def index_object(self, documentId, obj, threshold=None):
        """ wrapper to handle indexing of multiple attributes """

        res = self._index_object(documentId, obj, threshold)

        return res


    def _index_object(self, documentId, obj, threshold=None):
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
        newUKeywords = self._get_permuted_keywords(obj)
                
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


    def unindex_objectKeywords(self, documentId, keywords):
        """ carefully unindex the object with integer id 'documentId'"""

        if keywords is not None:
            for kw in keywords:
                self.removeForwardIndexEntry(kw, documentId)

    def unindex_object(self, documentId):
        """ carefully unindex the object with integer id 'documentId'"""

        keywords = self._unindex.get(documentId, None)
        self.unindex_objectKeywords(documentId, keywords)
        try:
            del self._unindex[documentId]
        except KeyError:
            logger.debug('Attempt to unindex nonexistent'
                         ' document id %s' % documentId)    


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
        
    def _get_permuted_keywords(self, obj):
        """ returns permutation list of object keywords """    

        components = self.getIndexComponents()
         
        kw_list = []
        
        for c in components:
            kw=self._get_keywords(obj, c)
            kw_list.append(kw)
        
        pkl = PermuteKeywordList(kw_list)

        return pkl.keys


    def _get_keywords(self,obj,component):

        if component.type == 'FieldIndex':
            attr = component.attributes[-1]
            try:
                datum = getattr(obj, attr)
                if safe_callable(datum):
                    datum = datum()
            except (AttributeError, TypeError):
                datum = _marker
            if isinstance(datum,list):
                datum = tuple(datum)
            return (datum,)

        elif component.type == 'KeywordIndex':
            for attr in component.attributes:
                datum = []
                newKeywords = getattr(obj, attr, ())
                if safe_callable(newKeywords):
                    try:
                        newKeywords = newKeywords()
                    except AttributeError:
                        continue
                if not newKeywords and newKeywords is not False:
                    continue
                elif isinstance(newKeywords, basestring): #Python 2.1 compat isinstance
                    datum.append(newKeywords)
                else:
                    unique = {}
                    try:
                        for k in newKeywords:
                            unique[k] = None
                    except TypeError:
                        # Not a sequence
                        datum.append(newKeywords)
                    else:
                        datum.extend(unique.keys())
            return datum
        else:
            raise KeyError

    def getIndexComponents(self):
        """ return sequence of indexed attributes """
        return self._components.values()

 
    def getComponentIndexNames(self):
        """ returns component index names to composite """

        return self._components.keys()

    def getComponentIndexAttributes(self):
        """ returns list of attributes of each component index to composite"""

        return tuple([a.attributes for a in self._components.values()])


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


    def hasUniqueValuesFor(self, name):
        """has unique values for column name"""
        if name in self.getComponentIndexNames():
            return 1
        else:
            return 0

    def uniqueValues(self, name=None, withLengths=0):
        """returns the unique values for name

        if withLengths is true, returns a sequence of
        tuples of (value, length)
        """

        # default: return unique values from first component

        if name is None: 
            return super(CompositeIndex,self).uniqueValues( name=name, withLengths=withLengths)

        
        if self._cindexes.has_key(name):
            index = self._cindexes[name]
        else:
            return []

        if not withLengths:
            return tuple(index.keys())
        else:
            rl=[]
            for i in index.keys():
                set = index[i]
                if isinstance(set, int):
                    l = 1
                else:
                    l = len(set)
                rl.append((i, l))
            return tuple(rl)

    
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


    def make_query(self, query):
        """ optimize the query """
        
        cquery = query.copy()

        components = self.getIndexComponents()

        records=[]
 
        for c in components:
            query_options = QUERY_OPTIONS[c.type]
            rec = parseIndexRequest(query, c.id, query_options)

            if rec.keys is None:
                continue

            records.append((c.id, rec))

        if not records:
            return query

        cquery.update( { self.id: { 'query': records }} )
                    
        # delete obsolete query attributes from request
        for i in [ r[0] for r in records ]:
            if cquery.has_key(i):
                del cquery[i]

        logger.debug('composite query build "%s"' % cquery)
        
        return cquery

    manage = manage_main = DTMLFile('dtml/manageCompositeIndex', globals())
    manage_main._setName('manage_main')
    manage_browse = DTMLFile('dtml/browseIndex', globals())


manage_addCompositeIndexForm = DTMLFile('dtml/addCompositeIndex', globals())

def manage_addCompositeIndex(self, id, extra=None,
                REQUEST=None, RESPONSE=None, URL3=None):
    """Add a composite index"""
    return self.manage_addIndex(id, 'CompositeIndex', extra=extra, \
             REQUEST=REQUEST, RESPONSE=RESPONSE, URL1=URL3)


    

        

