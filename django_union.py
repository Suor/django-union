from collections import defaultdict

from django.db.models.loading import get_model
from django.db.models.query import QuerySet
from django.db.models import Manager
from handy.db import fetch_all


class Union(object):
    def __init__(self, *querysets):
        assert querysets, "Union should be non-empty"
        self.querysets = tuple(qs if isinstance(qs, (QuerySet, Manager)) else qs.objects
                               for qs in querysets)
        self.ordering = None

    def count(self):
        return sum(q.count() for q in self.querysets)

    def __getitem__(self, k):
        assert isinstance(k, slice) and not k.step, "Only simple slices supported"

        rows = fetch_all(*self._union_sql(k.start, k.stop))
        id_groups = _group_rows(rows)
        obj_map = {
            (model, pk): obj
            for model, pks in id_groups.items()
            for pk, obj in _get_model(model).objects.in_bulk(pks).items()
        }
        return map(obj_map.get, rows)

    def _union_sql(self, start=None, stop=None):
        sql, params = zip(*map(_sql_with_params, self.querysets))
        sql = ' union all '.join(sql)
        params = sum(params, ())

        # TODO: dehardcode posted
        sql = 'select model, id from (%s) foo order by posted desc' % sql

        # Add LIMIT/OFFSET
        if start:
            sql += ' offset %s'
            params += (start,)
        if stop:
            sql += ' limit %s'
            params += (stop - (start or 0),)

        return sql, params

    ### "Queryset" updating methods

    def _clone(self):
        clone = self.__class__(*self.querysets)
        clone.ordering = self.ordering # It's tuple, no need to copy
        return clone

    def _proxy_method(name):
        def _method(self, *args, **kwargs):
            clone = self._clone()
            clone.querysets = [getattr(qs, name)(*args, **kwargs) for qs in clone.querysets]
            return clone
        _method.__name__ = name
        return _method

    filter = _proxy_method('filter')
    extra = _proxy_method('extra') # NOTE: order_by not supported
    select_related = _proxy_method('select_related')

    # NOTE: not really working, posted order is hardcoded for now
    def order_by(self, *args):
        clone = self._clone()
        clone.ordering = args
        return clone


def _sql_with_params(qs):
    opts = qs.model._meta
    model_str = '%s.%s' % (opts.app_label, opts.model_name)
    qs = qs.extra(select={'model': "'%s'" % model_str}).values('id', 'model', 'posted').order_by()
    return qs.query.sql_with_params()


def _group_rows(rows):
    groups = defaultdict(list)
    for model, pk in rows:
        groups[model].append(pk)
    return groups


def _get_model(full_name):
    return get_model(*full_name.split('.'))
