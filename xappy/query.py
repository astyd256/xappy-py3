# Copyright (C) 2008,2009 Lemur Consulting Ltd
# Copyright (C) 2009 Richard Boulton
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
r"""query.py: Query representations.

"""
__docformat__ = "restructuredtext en"

from . import _checkxapian
import copy
import xapian

class Query(object):
    """A query.

    """

    OP_AND = xapian.Query.OP_AND
    OP_OR = xapian.Query.OP_OR

    def __init__(self, query=None, _refs=None, _conn=None, _ranges=None,
                 _serialised=None, _queryid=None):
        """Create a new query.

        If `query` is a xappy.Query, or xapian.Query, object, the new query is
        initialised as a copy of the supplied query.

        """
        # Copy _refs, and make sure it's a list.
        if _refs is None:
            _refs = []
        else:
            _refs = [ref for ref in _refs]

        if _ranges is None:
            _ranges = []
        else:
            _ranges = [tuple(range) for range in _ranges]

        if query is None:
            query = xapian.Query()
            if _serialised is None:
                _serialised = 'Query()'

        # Set the default query parameters.
        self.__op = None
        self.__subqs = None

        if isinstance(query, xapian.Query):
            self.__query = query
            self.__refs = _refs
            self.__conn = _conn
            self.__ranges = _ranges
            self.__serialised = _serialised
            self.__cacheinfo = (_queryid, self)
            self.__search_params = {}
        else:
            # Assume `query` is a xappy.Query() object.
            self.__query = query.__query
            self.__refs = _refs
            self.__conn = _conn
            self.__ranges = _ranges
            if _serialised is None:
                self.__serialised = query.__serialised
            else:
                self.__serialised = _serialised
            self.__cacheinfo = (_queryid, self)
            self.__search_params = copy.deepcopy(query.__search_params)
            self.__merge_params(query)

    def empty(self):
        """Test if the query is empty.

        A empty query contains no terms or other sources of documents, and will
        thus match no documents.

        An empty query may be constructed by the default constructor, or by
        composing an empty list.

        """
        return self.__query.empty()

    def is_composable(self):
        """Test if the query can be composed with another query.

        This will be True for most plain queries.  However, queries with some
        parameters (such as those indicating desired facets), cannot be
        composed with other queries.  An error will be raised if an attempt is
        made to compose such queries.

        """
        if len(self.__search_params) != 0:
            return False
        return True

    def _check_composable(self):
        """Check that this subquery is composable with others, and raise an
        error if it isn't.

        """
        if not self.is_composable():
            raise ValueError("Can't compose this query with other queries.")

    def __merge_params(self, query):
        """Merge the parameters in this query with those in another query.

        """
        # Check that the connection is compatible.
        if self.__conn is not query.__conn:
            if self.__conn is None:
                self.__conn = query.__conn
            elif query.__conn is not None:
                raise ValueError("Queries are not from the same connection")

        # Combine the refs
        self.__refs.extend(query.__refs)

        # Combine the ranges
        for range in query.__ranges:
            if range not in self.__ranges:
                self.__ranges.append(range)

    @staticmethod
    def compose(operator, queries):
        """Build and return a composite query from a list of queries.

        The queries are combined with the supplied operator, which is either
        Query.OP_AND or Query.OP_OR.

        `queries` is any iterable which returns a list of queries (either
        xapian.Query or xappy.Query objects).

        As a convenience, the list of queries may also contain entries which
        are "None" - such entries will be filtered out and ignored.

        If the list of queries is empty, this will return an empty Query; ie,
        one which will match no documents.

        """
        queries = tuple(filter(lambda x: x is not None, queries))

        # Special cases for 0 or 1 subqueries - don't build pointless
        # combinations.
        if len(queries) == 0:
            return Query()
        elif len(queries) == 1:
            return Query(queries[0])

        # Check that the queries are ok to compose with others.
        for q in queries:
            if hasattr(q, '_check_composable'):
                q._check_composable()

        # flatten the queries: any subqueries in the list which are also
        # combination queries with the same operator should be merged into this
        # combination query.
        flattened_queries = []
        for q in queries:
            if not isinstance(q, xapian.Query) and q.__op == operator:
                flattened_queries.extend(q.__subqs)
            else:
                flattened_queries.append(q)

        result = Query()
        result.__op = operator
        result.__subqs = flattened_queries

        xapqs = []
        serialisedqs = []
        for q in flattened_queries:
            if isinstance(q, xapian.Query):
                xapqs.append(q)
                serialisedqs = None
            elif isinstance(q, Query):
                xapqs.append(q.__query)
                if serialisedqs is not None:
                    serialisedq = q.__serialised
                    if serialisedq is None:
                        serialisedqs = None
                    else:
                        serialisedqs.append(serialisedq)
                result.__merge_params(q)
            else:
                raise TypeError("queries must contain a list of xapian.Query or xappy.Query objects")

        result.__query = xapian.Query(operator, xapqs)
        if serialisedqs is not None:
            if len(serialisedqs) == 0:
                result.__serialised = "Query()"
            elif len(serialisedqs) == 1:
                result.__serialised = serialisedqs[0]
            elif len(serialisedqs) == 2:
                result.__serialised = '(' + {
                    Query.OP_AND: ' & ',
                    Query.OP_OR: ' | ',
                }[operator].join(serialisedqs) + ')'
            else:
                operator_str = {
                    Query.OP_AND: 'Query.OP_AND',
                    Query.OP_OR: 'Query.OP_OR',
                }[operator]
                result.__serialised = "Query.compose(" + operator_str + \
                                      ", (" + ', '.join(serialisedqs) + "))"

        return result

    def __mul__(self, multiplier):
        """Return a query with the weight scaled by multiplier.

        """
        result = Query()
        result.__merge_params(self)
        self._check_composable()
        if self.__serialised is not None:
            result.__serialised = '(' + self.__serialised + " * " + repr(multiplier) + ')'
        try:
            result.__query = xapian.Query(xapian.Query.OP_SCALE_WEIGHT,
                                          self.__query, multiplier)
        except TypeError:
            return NotImplemented
        return result

    def __rmul__(self, lhs):
        """Return a query with the weight scaled by multiplier.

        """
        return self.__mul__(lhs)

    def __div__(self, rhs):
        """Return a query with the weight divided by a number.

        """
        try:
            return self.__mul__(1.0 / rhs)
        except TypeError:
            return NotImplemented

    def __truediv__(self, rhs):
        """Return a query with the weight divided by a number.

        """
        try:
            return self.__mul__(1.0 / rhs)
        except TypeError:
            return NotImplemented

    def __and__(self, other):
        """Return a query combined using AND with another query.

        """
        if not isinstance(other, (Query, xapian.Query)):
            return NotImplemented
        return Query.compose(Query.OP_AND, (self, other))

    def __or__(self, other):
        """Return a query combined using OR with another query.

        """
        if not isinstance(other, (Query, xapian.Query)):
            return NotImplemented
        return Query.compose(Query.OP_OR, (self, other))

    def __xor__(self, other):
        """Return a query combined using XOR with another query.

        """
        if not isinstance(other, (Query, xapian.Query)):
            return NotImplemented
        return self.__combine_with(xapian.Query.OP_XOR, other)

    def __combine_with(self, operator, other):
        """Return the result of combining this query with another query.

        """
        result = Query(self)
        self._check_composable()
        if isinstance(other, xapian.Query):
            oquery = other
        elif isinstance(other, Query):
            other._check_composable()
            oquery = other.__query
            result.__merge_params(other)
            if self.__serialised is not None and other.__serialised is not None:
                funcname = {
                    xapian.Query.OP_XOR: ".xor",
                    xapian.Query.OP_AND_NOT: ".and_not",
                    xapian.Query.OP_FILTER: ".filter",
                    xapian.Query.OP_AND_MAYBE: ".adjust",
                }[operator]
                result.__serialised = ''.join((self.__serialised, funcname,
                                               '(' + other.__serialised + ')'))
        else:
            raise TypeError("other must be a xapian.Query or xappy.Query object")

        result.__query = xapian.Query(operator, self.__query, oquery)

        return result

    def xor(self, other):
        return self.__combine_with(xapian.Query.OP_XOR, other)

    def and_not(self, other):
        """Return a query which returns filtered results of this query.

        The query will return only those results which aren't also matched by
        `other`, which should also be a query.

        """
        return self.__combine_with(xapian.Query.OP_AND_NOT, other)

    def filter(self, other):
        """Return a query which returns filtered results of this query.

        The query will return only those results which are also matched by
        `other`, which should also be a query, but the weights of the results will not be modified by those
        from `other`.

        """
        return self.__combine_with(xapian.Query.OP_FILTER, other)

    def adjust(self, other):
        """Return a query with this query's weights adjusted by another query.

        Documents will be returned from the resulting query if and only if they
        match this query.  However, the weights of the resulting documents will
        be adjusted by adding weights from the secondary query (specified by
        the `other` parameter).

        Note: this method is available both as "adjust" and as "and_maybe".

        """
        return self.__combine_with(xapian.Query.OP_AND_MAYBE, other)

    # Add "and_maybe" as an alternative name for "adjust", since this name is
    # familiar to people with a Xapian background.
    and_maybe = adjust

    def get_max_possible_weight(self):
        """Calculate the maximum possible weight returned by this query.

        See `SearchConnection.get_max_possible_weight()` for more details.

        """
        if self.empty():
            return 0
        if self.__conn is None:
            raise ValueError("This Query is not associated with a SearchConnection")

        return self.__conn.get_max_possible_weight(self)

    def norm(self, maxweight=1.0):
        """Normalise the possible weights returned by a query.

        This will return a new Query, which returns the same documents as this
        query, but for which the weights will fall strictly in the range 0..1.
        (Or the range 0..maxweight if maxweight is specified.)

        This is equivalent to dividing the query by the result of
        `get_max_possible_weight()`, except that the case of the maximum
        possible weight being 0 is handled correctly.  The serialised
        representation of the query is also nicer if norm is used() than when
        dividing by get_max_possible_weight (in that it usually won't contain
        long floating point number representations).

        Note that it will be very rare for a resulting document to attain a
        weight of 1.0.

        """
        max_possible = self.get_max_possible_weight()
        if max_possible > 0.:
            result = self * (maxweight / max_possible)
            if maxweight == 1.0:
                result.__serialised = self.__serialised + '.norm()'
            else:
                result.__serialised = self.__serialised + '.norm(' + repr(maxweight) + ')'
            return result
        return self

    def merge_with_cached(self, cached_id):
        """Merge this query with cached results.

        `cached_id` is a cached query ID to use.

        """
        if self.__conn is None:
            raise ValueError("This Query is not associated with a SearchConnection")
        result = self.norm() | self.__conn.query_cached(cached_id)
        result.__serialised = self.__serialised + \
            '.merge_with_cached(%d)' % cached_id
        result.__cacheinfo = (cached_id, self)
        return result

    def search(self, startrank, endrank, *args, **kwargs):
        """Perform a search using this query.

        - `startrank` is the rank of the start of the range of matching
          documents to return (ie, the result with this rank will be returned).
          ranks start at 0, which represents the "best" matching document.
        - `endrank` is the rank at the end of the range of matching documents
          to return.  This is exclusive, so the result with this rank will not
          be returned.

        Additional arguments and keyword arguments may be specified.  These
        will be interpreted as by SearchConnection.search().

        """
        if self.__conn is None:
            raise ValueError("This Query is not associated with a SearchConnection")

        return self.__conn.search(self, startrank, endrank, *args, **kwargs)

    def _get_xapian_query(self):
        """Get the query as a xapian object.

        This is intended for internal use in xappy only.

        If you _must_ use it outside xappy, note in particular that the xapian
        query will only remain valid as long as this object is valid.  Using it
        after this object has been deleted may result in invalid memory access
        and segmentation faults.

        """
        return self.__query

    def _get_terms(self):
        """Get a list of the terms in the query.

        This is intended for internal use in xappy only.

        """
        qtermiter = xapian.TermIter(self.__query.get_terms_begin(),
                                    self.__query.get_terms_end())
        return [item.term for item in qtermiter]

    def _get_ranges(self):
        """Get a list of the ranges in the query.

        This is intended for internal use in xappy only.

        The return type is a tuple of items, where each item consists of
        (fieldname, start, end)

        """
        return self.__ranges

    def evalable_repr(self):
        """Return a serialised form of this query, suitable for eval.

        This form can be passed to eval to get back the unserialised query,
        though this must be done in a context in which the following symbols
        are defined:
        
         - "conn" is a symbol defined to be the search connection which the query is associated with.
         - "xapian" is the "xapian" module.
         - "xappy" is the "xappy" module.
         - "Query" is the "xappy.Query" class.
        
        A convenient method to do this is the
        SearchConnection.query_from_evalable() method.

        If the query was originally created by passing a raw xapian query to
        the query constructor, the serialised form cannot be computed, and this
        method will return None.

        """
        return self.__serialised

    def _set_serialised(self, serialised):
        """Set the serialised form of this query.

        This is intended for internal use in xappy only.

        """
        self.__serialised = serialised

    def _get_queryid(self):
        """Get the queryid if the query is a cached query.

        Returns None if it's not a cached query.

        """
        return self.__cacheinfo[0]

    def _get_original_query(self):
        """Get the version of the query which doesn't have the cache applied.

        """
        return self.__cacheinfo[1]

    def __str__(self):
        return str(self.__query)

    def __repr__(self):
        return "<xappy.Query(%s)>" % str(self.__query)

    def get_facet(self, fieldname, checkatleast=None,
                  desired_num_of_categories=None):
        """Mark a facet as wanted.

         - `fieldname` is the name of the field to get facets from.
         - `checkatleast` is the minimum number of potential matches to check
           when counting for this facet.
         - `desired_num_of_categories` is the ideal number of categories wanted
           for this facet.

        This will return a new Query, which returns the same documents as this
        query, but will cause facets in the named field to be counted.  The
        result of this counting can be obtained using the get_facets() method
        on the SearchResult object.

        The resulting Query can not be combined with other Queries.

        An error will be raised, either immediately or when the search is
        performed, if the specified fieldname is not indexed for faceting.

        """
        return self.get_facets((fieldname,), checkatleast,
                               desired_num_of_categories)

    def get_facets(self, fieldnames, checkatleast=None,
                   desired_num_of_categories=None):
        """Mark a set of fieldnames as wanted.

         - `fieldnames` is an iterable of fieldnames.
         - `checkatleast` is the minimum number of potential matches to check
           when counting for this facet.
         - `desired_num_of_categories` is the ideal number of categories wanted
           for this facet.

        This will return a new Query, which returns the same documents as this
        query, but will cause facets in the named fields to be counted.  The
        result of this counting can be obtained using the get_facets() method
        on the SearchResult object.

        The resulting Query can not be combined with other Queries.

        An error will be raised, either immediately or when the search is
        performed, if the specified fieldname is not indexed for faceting.

        """
        result = Query(self)
        facets = result.__search_params.setdefault('facets', {'invert': False})
        if facets['invert']:
            raise ValueError("get_facets() called on Query for which "
                             "get_facets_except() had already been called")

        fields = facets.setdefault('fields', {})
        fieldnames = tuple(fieldnames)
        for fieldname in fieldnames:
            fields[fieldname] = (checkatleast, desired_num_of_categories)

        result.__serialised = ''.join((self.__serialised, '.get_facets(',
                                      repr(fieldnames), ', ',
                                      repr(checkatleast), ', ',
                                      repr(desired_num_of_categories), ')'))
        return result

    def get_facets_except(self, fieldnames, checkatleast=None,
                          desired_num_of_categories=None):
        """Mark a query as wanting all facets except those listed.

         - `fieldnames` is an iterable of fieldnames.
         - `checkatleast` is the minimum number of potential matches to check
           when counting for this facet.
         - `desired_num_of_categories` is the ideal number of categories wanted
           for this facet.

        This will return a new Query, which returns the same documents as this
        query, but will cause facets in all facet fields apart from the named
        fields to be counted.  The result of this counting can be obtained
        using the get_facets() method on the SearchResult object.

        The resulting Query can not be combined with other Queries.

        An error will be raised, either immediately or when the search is
        performed, if the specified fieldnames are not indexed for faceting.

        """
        result = Query(self)
        facets = result.__search_params.setdefault('facets', {'invert': True})
        if not facets['invert']:
            raise ValueError("get_facets_except() called on Query for which "
                             "get_facets() had already been called")
        fields = facets.setdefault('fields', {})
        fieldnames = tuple(fieldnames)
        for fieldname in fieldnames:
            fields[fieldname] = (None, None)

        result.__serialised = ''.join(self.__serialised, '.get_facets(',
                                      repr(fieldnames), ')')
        return result
