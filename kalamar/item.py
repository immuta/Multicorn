# -*- coding: utf-8 -*-
# This file is part of Dyko
# Copyright © 2008-2009 Kozea
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kalamar.  If not, see <http://www.gnu.org/licenses/>.

"""
Base classes to create kalamar items.

Parsers must:
- inherit from Item
- have a ``format`` class attribute as a string,
- extend or override the _parse_data method,
- override the serialize method.

The ``format`` string is used to identify the parser in configuration files
and must be unique.

See BinaryItem for a very simple example.

"""

from werkzeug import MultiDict, cached_property
    
from kalamar import parser, utils
from kalamar.requestparser import reverse_convert_value



class Item(object):
    """Base class for parsers.
    
    Items dictionnary-like: you can use the item['…'] syntax to get and set
    properties. Missing properties default to None.
    
    The _access_point attribute represents where, in kalamar, the item is
    stored. It is an instance of AccessPoint.

    Items are hashable but mutable, use hash with caution.

    """
    # TODO: use the MultiDict power by coding getlist/setlist (or not?)
    format = None

    def __init__(self, access_point, opener=None, storage_properties={}):
        """This constructor should not be used directly.
        Get items from AccessPoint’s or use Item.create_item to create them.
        
        Parameters:
        - access_point: an instance of the AccessPoint class.
        - opener: a function taking no parameters and returning the item raw
          “content” as a bytestring, or the empty string.
        - storage_properties: properties generated by the storage for this
          item.
        
        """
        self._opener = opener or str
        self._raw_content = None
        self._raw_content_mimetype = None
        self._access_point = access_point
        self._access_point_name = None
        self.storage_modified = False
        self.parser_modified = False
        self._request = None
        
        # Used when an item is contained into a capsule
        self.association_properties = {}
        
        
        self.storage_aliases = dict(access_point.storage_aliases)
        self.parser_aliases = dict(access_point.parser_aliases)
        
        self.raw_storage_properties = MultiDict(storage_properties)
        
        # Keep this one to track modifications made to raw_parser_properties
        self.old_storage_properties = MultiDict(storage_properties)

        self.storage_properties = utils.AliasedMultiDict(
            self.raw_storage_properties, self.storage_aliases)
        
    @cached_property
    def raw_parser_properties(self):
        """The “parser” counterpart of raw_storage_properties. A MultiDict.
        
        Parser properties are lazy: only parse when needed.

        """
        return MultiDict(self._parse_data())

    @cached_property
    def parser_properties(self):
        """The “parser” counterpart of storage_properties.
        
        This is also a cached_property because we need the actual
        raw_parser_properties MultiDict to instanciate it.

        """
        return utils.AliasedMultiDict(self.raw_parser_properties,
                                      self.parser_aliases)

    def _is_storage_key(self, key):
        """Determine wether this key is storage property or parser property."""
        if key in self.storage_aliases:
            return True
        if key in self.parser_aliases:
            return False
        return key in self.storage_properties
    
    def __getitem__(self, key):
        """Return the item ``key`` property."""
        try:
            if self._is_storage_key(key):
                return self.storage_properties[key]
            else:
                return self.parser_properties[key]
        except KeyError:
            return None
    
    def __setitem__(self, key, value):
        """Set the item ``key`` property to ``value``."""
        if self._is_storage_key(key):
            self.storage_properties[key] = value
            self.storage_modified = True
        else:
            self.parser_properties[key] = value
            self.parser_modified = True

    def __eq__(self, item):
        """Test if ``item`` is the same as this item."""
        if isinstance(item, Item):
            return hash(item) == hash(self)
        return NotImplemented

    # TODO test
    def __cmp__(self, item):
        """Compare two items.
        
        Useful in some algorithms (sorting by key, for example).
        DO NOT USE UNLESS YOU KNOW WHAT YOU'RE DOING!
        
        """
        if isinstance(item, Item):
            str1 = hash(self)
            str2 = hash(item)
            return cmp(str1, str2)
        return NotImplemented

    def __repr__(self):
        """Return a user-friendly representation of item."""
        values = (self.__class__.__name__,
                  repr(self.request),
                  repr(self.access_point_name))
        return '<%s(%s @ %s)>' % values
    
    def __hash__(self):
        """Return a hash of item.
        
        Do not forget that items are mutable, so the hash could change!
        
        This hash value is useful in some algorithms (eg in sets) and it
        permits a huge gain of performance. However, DON'T USE THIS HASH UNLESS
        YOU KNOW WHAT YOU'RE DOING.
        
        """
        return hash(self.access_point_name + self.request)

    @staticmethod
    def create_item(access_point, properties=None, initial_content=None):
        """Return a new item instance.
        
        Parameters:
        - ``access_point``: instance of the access point where the item
          will be reachable (after saving).
        - ``properties``: dictionnary or MultiDict of the item properties.
          These properties must be coherent with what is defined for the
          access point.
        - ``initial_content``: some initial content for parsers needing it.
        
        Fixture
        >>> from _test.corks import CorkAccessPoint
        >>> ap = CorkAccessPoint()
        >>> properties = {}
        
        Test
        >>> item = Item.create_item(ap, properties)
        >>> assert item.format == ap.parser_name
        >>> assert isinstance(item, Item)
        
        """
        storage_properties = dict((name, None) for name
                                  in access_point.get_storage_properties())
        
        item_parser = Item._find_parser(access_point)
        item = item_parser(access_point,
                           storage_properties=storage_properties,
                           opener=lambda: initial_content)
        
        # old_storage_properties is meaningless for a new item.
        item.old_storage_properties = MultiDict()
                
        if properties:
            for name, value in properties.items():
                item[name] = value

        return item

    @staticmethod
    def _find_parser(access_point):
        """Return the parser class set for the given access point.
        
        Your kalamar distribution should have, at least, a parser for the
        ``binary`` format.
        
        >>> from _test.corks import CorkAccessPoint
        >>> ap = CorkAccessPoint()
        >>> ap.parser_name = 'binary'
        >>> Item._find_parser(ap)
        <class 'kalamar.item.BinaryItem'>
        
        An invalid format will raise a ValueError:
        >>> ap.parser_name = 'I do not exist'
        >>> Item._find_parser(ap)
        Traceback (most recent call last):
        ...
        ParserNotAvailable: Unknown parser: I do not exist
        
        """
        parser.load()
        
        if access_point.parser_name is None:
            return Item
        
        for subclass in utils.recursive_subclasses(Item):
            if getattr(subclass, 'format', None) == access_point.parser_name:
                return subclass
        
        raise utils.ParserNotAvailable('Unknown parser: ' +
                                       access_point.parser_name)

    @property
    def encoding(self):
        """Return the item encoding.

        Return the item encoding, based on what the parser can know from
        the item data or, if unable to do so, on what is specified in the
        access_point.

        """
        return self._access_point.default_encoding
    
    @property
    def modified(self):
        """Return if the item has been modified since creation.

        The item is considered changed if any storage or parser property has
        been changed since its creation.

        """
        return self.storage_modified or self.parser_modified
    
    @property
    def filename(self):
        """Return the file path.

        If the item is stored in a file, return its path/name.
        Else return None.

        """
        if hasattr(self._access_point, 'filename_for'):
            return self._access_point.filename_for(self)
    
    @property
    def request(self):
        """Return a request sufficient to find this item and only this one.

        This ``request`` must be canonical. As a consequence, opening an item
        twice should give the same ``request``, even if the request used for
        opening the items are not the same.

        This property is used for testing item equality.

        """
        if self._request is None:
            conditions = [
                u'%s=%s' % (key, reverse_convert_value(self[key]))
                for key in self._access_point.primary_keys]
            self._request = '/'.join(conditions)
        return self._request
    
    @property
    def access_point_name(self):
        """Return a request sufficient to find this item and only this one."""
        if self._access_point_name is None:
            self._access_point_name = self._access_point.name
        return self._access_point_name

    def keys(self):
        """Return the name of all properties."""
        # Use a set to make keys unique
        return list(set(self.storage_properties.keys() +
                        self.parser_properties.keys()))

    def _parse_data(self):
        """Parse properties from data, return a dictionnary (MultiDict).
        
        This method should use ``self._get_content()`` parse the result,
        and return a MultiDict.

        """
        return MultiDict()

    def serialize(self):
        """Return raw content as bytestring."""
        return ''

    def test_condition(self, condition):
        """Return True if item properties matches this condition."""
        return condition.operator(
            self[condition.property_name], condition.value)

    def _get_content(self):
        """Return the raw content as a bytestring, to be parsed."""
        if self._raw_content is None:
            self._raw_content = self._opener() or ''
        return self._raw_content



class BinaryItem(Item):
    """Simple parser giving access to raw content as ``data`` property."""
    format = 'binary'
    
    def _parse_data(self):
        """Parse the whole item content."""
        return MultiDict(data=self._get_content())
        
    def serialize(self):
        """Return the item content."""
        return self.raw_parser_properties['data']



class CapsuleItem(Item):
    """An ordered list of Items (atoms or capsules).

    This is an abstract class.
    Subclasses need to override the ``_load_subitems`` method.

    """
    def __init__(self, access_point, opener=None, storage_properties={}):
        """Return an instance of CapsuleItem.
        
        Parameters:
        - access_point: an instance of the AccessPoint class.
        - opener: a function taking no parameters and returning file-like
          object.
        - storage_properties: properties generated by the storage for this
          item.
        
        """
        super(CapsuleItem, self).__init__(
            access_point, opener, storage_properties)
        self._parser_modified = False
    
    def _get_subitems(self):
        """List of the capsule subitems."""
        if not hasattr(self, '_subitems'):
            self._subitems = utils.ModificationTrackingList(
                self._load_subitems())
        return self._subitems
    
    def _set_subitems(self, new_list):
        """Set the list of the capsule subitems."""
        self._subitems = utils.ModificationTrackingList(new_list)
        self._subitems.modified = True
    
    subitems = property(_get_subitems, _set_subitems)
        
    def _get_parser_modified(self):
        """Capsule parser_modified getter.

        This getter assumes that the capsule content is modified when:
        - one subitem (parser or storage) property has been modified, or
        - one capsule parser property has been modified.

        This situation should be right for most cases, particularly if the
        whole subitems are embedded in the capsule (movies, archives, etc.).

        If the subitems are just linked (ReStructuredText, etc.), this should
        work too but could be optimized. You can override this function by
        ``return self._parser_modified`` in this case.

        """
        return self._parser_modified or self.subitems.modified

    def _set_parser_modified(self, value):
        """Capsule parser_modified setter."""
        self._parser_modified = value
        
    parser_modified = property(_get_parser_modified, _set_parser_modified)

    def _load_subitems(self):
        """Load and return capsule subitems."""
        raise NotImplementedError('Abstract class')
