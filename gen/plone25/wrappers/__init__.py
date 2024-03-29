'''This package contains base classes for wrappers that hide to the Appy
   developer the real classes used by the underlying web framework.'''

# ------------------------------------------------------------------------------
import os, os.path, time, mimetypes, random
import appy.pod
from appy.gen import Search
from appy.gen.utils import sequenceTypes
from appy.shared.utils import getOsTempFolder, executeCommand, normalizeString
from appy.shared.xml_parser import XmlMarshaller
from appy.shared.csv_parser import CsvMarshaller

# Some error messages ----------------------------------------------------------
WRONG_FILE_TUPLE = 'This is not the way to set a file. You can specify a ' \
    '2-tuple (fileName, fileContent) or a 3-tuple (fileName, fileContent, ' \
    'mimeType).'
FREEZE_ERROR = 'Error while trying to freeze a "%s" file in POD field ' \
    '"%s" (%s).'
FREEZE_FATAL_ERROR = 'A server error occurred. Please contact the system ' \
    'administrator.'

# ------------------------------------------------------------------------------
class AbstractWrapper:
    '''Any real Zope object has a companion object that is an instance of this
       class.'''
    def __init__(self, o): self.__dict__['o'] = o
    def appy(self): return self

    def __setattr__(self, name, value):
        appyType = self.o.getAppyType(name)
        if not appyType:
            raise 'Attribute "%s" does not exist.' % name
        appyType.store(self.o, value)

    def __repr__(self):
        return '<%s appyobj at %s>' % (self.klass.__name__, id(self))

    def __cmp__(self, other):
        if other: return cmp(self.o, other.o)
        return 1

    def _callCustom(self, methodName, *args, **kwargs):
        '''This wrapper implements some methods like "validate" and "onEdit".
           If the user has defined its own wrapper, its methods will not be
           called. So this method allows, from the methods here, to call the
           user versions.'''
        if len(self.__class__.__bases__) > 1:
            # There is a custom user class
            customUser = self.__class__.__bases__[-1]
            if customUser.__dict__.has_key(methodName):
                return customUser.__dict__[methodName](self, *args, **kwargs)

    def get_tool(self): return self.o.getTool().appy()
    tool = property(get_tool)

    def get_request(self): return self.o.REQUEST
    request = property(get_request)

    def get_session(self): return self.o.REQUEST.SESSION
    session = property(get_session)

    def get_typeName(self): return self.__class__.__bases__[-1].__name__
    typeName = property(get_typeName)

    def get_id(self): return self.o.id
    id = property(get_id)

    def get_uid(self): return self.o.UID()
    uid = property(get_uid)

    def get_klass(self): return self.__class__.__bases__[-1]
    klass = property(get_klass)

    def get_url(self): return self.o.absolute_url()
    url = property(get_url)

    def get_state(self): return self.o.getState()
    state = property(get_state)

    def get_stateLabel(self):
        appName = self.o.getProductConfig().PROJECTNAME
        return self.o.translate(self.o.getWorkflowLabel(), domain=appName)
    stateLabel = property(get_stateLabel)

    def get_history(self):
        key = self.o.workflow_history.keys()[0]
        return self.o.workflow_history[key]
    history = property(get_history)

    def get_user(self): return self.o.portal_membership.getAuthenticatedMember()
    user = property(get_user)

    def get_fields(self): return self.o.getAllAppyTypes()
    fields = property(get_fields)

    def getField(self, name): return self.o.getAppyType(name)

    def link(self, fieldName, obj):
        '''This method links p_obj (which can be a list of objects) to this one
           through reference field p_fieldName.'''
        postfix = 'et%s%s' % (fieldName[0].upper(), fieldName[1:])
        # Update the Archetypes reference field
        exec 'objs = self.o.g%s()' % postfix
        if not objs:
            objs = []
        elif type(objs) not in sequenceTypes:
            objs = [objs]
        # Add p_obj to the existing objects
        if type(obj) in sequenceTypes:
            for o in obj: objs.append(o.o)
        else:
            objs.append(obj.o)
        exec 'self.o.s%s(objs)' % postfix
        # Update the ordered list of references
        sorted = self.o._appy_getSortedField(fieldName)
        if type(obj) in sequenceTypes:
            for o in obj: sorted.append(o.o.UID())
        else:
            sorted.append(obj.o.UID())

    def unlink(self, fieldName, obj):
        '''This method unlinks p_obj (which can be a list of objects) from this
           one through reference field p_fieldName.'''
        postfix = 'et%s%s' % (fieldName[0].upper(), fieldName[1:])
        # Update the Archetypes reference field.
        exec 'objs = self.o.g%s()' % postfix
        if not objs: return
        if type(objs) not in sequenceTypes: objs = [objs]
        # Remove p_obj from existing objects
        if type(obj) in sequenceTypes:
            for o in obj:
                if o.o in objs: objs.remove(o.o)
        else:
            if obj.o in objs: objs.remove(obj.o)
        exec 'self.o.s%s(objs)' % postfix
        # Update the ordered list of references
        sorted = self.o._appy_getSortedField(fieldName)
        if type(obj) in sequenceTypes:
            for o in obj:
                if o.o.UID() in sorted:
                    sorted.remove(o.o.UID())
        else:
            if obj.o.UID() in sorted:
                sorted.remove(obj.o.UID())

    def sort(self, fieldName, sortKey='title', reverse=False):
        '''Sorts referred elements linked to p_self via p_fieldName according
           to a given p_sortKey which must be an attribute set on referred
           objects ("title", by default).'''
        sortedUids = getattr(self.o, '_appy_%s' % fieldName)
        c = self.o.uid_catalog
        sortedUids.sort(lambda x,y: \
           cmp(getattr(c(UID=x)[0].getObject().appy(), sortKey),
               getattr(c(UID=y)[0].getObject().appy(), sortKey)))
        if reverse:
            sortedUids.reverse()

    def create(self, fieldNameOrClass, **kwargs):
        '''If p_fieldNameOfClass is the name of a field, this method allows to
           create an object and link it to the current one (self) through
           reference field named p_fieldName.
           If p_fieldNameOrClass is a class from the gen-application, it must
           correspond to a root class and this method allows to create a
           root object in the application folder.'''
        isField = isinstance(fieldNameOrClass, basestring)
        # Determine the portal type of the object to create
        if isField:
            fieldName = idPrefix = fieldNameOrClass
            appyType = self.o.getAppyType(fieldName)
            portalType = self.tool.o.getPortalType(appyType.klass)
        else:
            klass = fieldNameOrClass
            idPrefix = klass.__name__
            portalType = self.tool.o.getPortalType(klass)
        # Determine object id
        if kwargs.has_key('id'):
            objId = kwargs['id']
            del kwargs['id']
        else:
            objId = '%s.%f.%s' % (idPrefix, time.time(),
                                  str(random.random()).split('.')[1])
        # Determine if object must be created from external data
        externalData = None
        if kwargs.has_key('_data'):
            externalData = kwargs['_data']
            del kwargs['_data']
        # Where must I create the object?
        if not isField:
            folder = self.o.getTool().getAppFolder()
        else:
            if hasattr(self, 'folder') and self.folder:
                folder = self.o
            else:
                folder = self.o.getParentNode()
        # Create the object
        folder.invokeFactory(portalType, objId)
        ploneObj = getattr(folder, objId)
        appyObj = ploneObj.appy()
        # Set object attributes
        for attrName, attrValue in kwargs.iteritems():
            setattr(appyObj, attrName, attrValue)
        if isField:
            # Link the object to this one
            self.link(fieldName, ploneObj)
            self.o.reindexObject()
        # Call custom initialization
        if externalData: param = externalData
        else: param = True
        if hasattr(appyObj, 'onEdit'): appyObj.onEdit(param)
        ploneObj.reindexObject()
        return appyObj

    def freeze(self, fieldName, doAction=False):
        '''This method freezes a POD document. TODO: allow to freeze Computed
           fields.'''
        rq = self.request
        field = self.o.getAppyType(fieldName)
        if field.type != 'Pod': raise 'Cannot freeze non-Pod field.'
        # Perform the related action if required.
        if doAction: self.request.set('askAction', True)
        # Set the freeze format
        rq.set('podFormat', field.freezeFormat)
        # Generate the document.
        doc = field.getValue(self.o)
        if isinstance(doc, basestring):
            self.log(FREEZE_ERROR % (field.freezeFormat, field.name, doc),
                     type='error')
            if field.freezeFormat == 'odt': raise FREEZE_FATAL_ERROR
            self.log('Trying to freeze the ODT version...')
            # Try to freeze the ODT version of the document, which does not
            # require to call OpenOffice/LibreOffice, so the risk of error is
            # smaller.
            self.request.set('podFormat', 'odt')
            doc = field.getValue(self.o)
            if isinstance(doc, basestring):
                self.log(FREEZE_ERROR % ('odt', field.name, doc), type='error')
                raise FREEZE_FATAL_ERROR
        field.store(self.o, doc)

    def unFreeze(self, fieldName):
        '''This method un freezes a POD document. TODO: allow to unfreeze
           Computed fields.'''
        rq = self.request
        field = self.o.getAppyType(fieldName)
        if field.type != 'Pod': raise 'Cannot unFreeze non-Pod field.'
        field.store(self.o, None)

    def delete(self):
        '''Deletes myself.'''
        self.o.delete()

    def translate(self, label, mapping={}, domain=None, language=None,
                  format='html'):
        '''Check documentation of self.o.translate.'''
        return self.o.translate(label, mapping, domain, language=language,
                                format=format)

    def do(self, transition, comment='', doAction=True, doNotify=True,
           doHistory=True):
        '''This method allows to trigger on p_self a workflow p_transition
           programmatically. See doc in self.o.do.'''
        return self.o.do(transition, comment, doAction=doAction,
                         doNotify=doNotify, doHistory=doHistory, doSay=False)

    def log(self, message, type='info'): return self.o.log(message, type)
    def say(self, message, type='info'): return self.o.say(message, type)

    def normalize(self, s, usage='fileName'):
        '''Returns a version of string p_s whose special chars have been
           replaced with normal chars.'''
        return normalizeString(s, usage)

    def search(self, klass, sortBy='', maxResults=None, noSecurity=False,
               **fields):
        '''Searches objects of p_klass. p_sortBy must be the name of an indexed
           field (declared with indexed=True); every param in p_fields must
           take the name of an indexed field and take a possible value of this
           field. You can optionally specify a maximum number of results in
           p_maxResults. If p_noSecurity is specified, you get all objects,
           even if the logged user does not have the permission to view it.'''
        # Find the content type corresponding to p_klass
        contentType = self.tool.o.getPortalType(klass)
        # Create the Search object
        search = Search('customSearch', sortBy=sortBy, **fields)
        if not maxResults:
            maxResults = 'NO_LIMIT'
            # If I let maxResults=None, only a subset of the results will be
            # returned by method executeResult.
        res = self.tool.o.executeQuery(contentType, search=search,
                                   maxResults=maxResults, noSecurity=noSecurity)
        return [o.appy() for o in res['objects']]

    def count(self, klass, noSecurity=False, **fields):
        '''Identical to m_search above, but returns the number of objects that
           match the search instead of returning the objects themselves. Use
           this method instead of writing len(self.search(...)).'''
        contentType = self.tool.o.getPortalType(klass)
        search = Search('customSearch', **fields)
        res = self.tool.o.executeQuery(contentType, search=search,
                                       brainsOnly=True, noSecurity=noSecurity)
        if res: return res._len # It is a LazyMap instance
        else: return 0

    def compute(self, klass, sortBy='', maxResults=None, context=None,
                expression=None, noSecurity=False, **fields):
        '''This method, like m_search and m_count above, performs a query on
           objects of p_klass. But in this case, instead of returning a list of
           matching objects (like m_search) or counting elements (like p_count),
           it evaluates, on every matching object, a Python p_expression (which
           may be an expression or a statement), and returns, if needed, a
           result. The result may be initialized through parameter p_context.
           p_expression is evaluated with 2 variables in its context: "obj"
           which is the currently walked object, instance of p_klass, and "ctx",
           which is the context as initialized (or not) by p_context. p_context
           may be used as
              (1) a variable or instance that is updated on every call to
                  produce a result;
              (2) an input variable or instance;
              (3) both.

           The method returns p_context, modified or not by evaluation of
           p_expression on every matching object.

           When you need to perform an action or computation on a lot of
           objects, use this method instead of doing things like
           
                    "for obj in self.search(MyClass,...)"
           '''
        contentType = self.tool.o.getPortalType(klass)
        search = Search('customSearch', sortBy=sortBy, **fields)
        # Initialize the context variable "ctx"
        ctx = context
        for brain in self.tool.o.executeQuery(contentType, search=search, \
                 brainsOnly=True, maxResults=maxResults, noSecurity=noSecurity):
            # Get the Appy object from the brain
            if noSecurity: method = '_unrestrictedGetObject'
            else: method = 'getObject'
            exec 'obj = brain.%s().appy()' % method
            exec expression
        return ctx

    def reindex(self):
        '''Asks a direct object reindexing. In most cases you don't have to
           reindex objects "manually" with this method. When an object is
           modified after some user action has been performed, Appy reindexes
           this object automatically. But if your code modifies other objects,
           Appy may not know that they must be reindexed, too. So use this
           method in those cases.'''
        self.o.reindexObject()

    def export(self, at='string', format='xml', include=None, exclude=None):
        '''Creates an "exportable" version of this object. p_format is "xml" by
           default, but can also be "csv". If p_format is:
           * "xml", if p_at is "string", this method returns the XML version,
                    without the XML prologue. Else, (a) if not p_at, the XML
                    will be exported on disk, in the OS temp folder, with an
                    ugly name; (b) else, it will be exported at path p_at.
           * "csv", if p_at is "string", this method returns the CSV data as a
                    string. If p_at is an opened file handler, the CSV line will
                    be appended in it.
           If p_include is given, only fields whose names are in it will be
           included. p_exclude, if given, contains names of fields that will
           not be included in the result.
        '''
        if format == 'xml':
            # Todo: take p_include and p_exclude into account.
            # Determine where to put the result
            toDisk = (at != 'string')
            if toDisk and not at:
                at = getOsTempFolder() + '/' + self.o.UID() + '.xml'
            # Create the XML version of the object
            marshaller = XmlMarshaller(cdata=True, dumpUnicode=True,
                                       dumpXmlPrologue=toDisk,
                                       rootTag=self.klass.__name__)
            xml = marshaller.marshall(self.o, objectType='appy')
            # Produce the desired result
            if toDisk:
                f = file(at, 'w')
                f.write(xml.encode('utf-8'))
                f.close()
                return at
            else:
                return xml
        elif format == 'csv':
            if isinstance(at, basestring):
                marshaller = CsvMarshaller(include=include, exclude=exclude)
                return marshaller.marshall(self)
            else:
                marshaller = CsvMarshaller(at, include=include, exclude=exclude)
                marshaller.marshall(self)

    def historize(self, data):
        '''This method allows to add "manually" a "data-change" event into the
           object's history. Indeed, data changes are "automatically" recorded
           only when an object is edited through the edit form, not when a
           setter is called from the code.

           p_data must be a dictionary whose keys are field names (strings) and
           whose values are the previous field values.'''
        self.o.addDataChange(data)

    def formatText(self, text, format='html'):
        '''Produces a representation of p_text into the desired p_format, which
           is 'html' by default.'''
        return self.o.formatText(text, format)
# ------------------------------------------------------------------------------
