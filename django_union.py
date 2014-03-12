from collections import defaultdict

from django.db.models.loading import get_model
from handy.db import fetch_all


class Union(object):
    def __init__(self, *querysets):
        assert querysets, "Union should be non-empty"
        self.querysets = querysets

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

    # TODO: .order_by()

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


def _sql_with_params(qs):
    opts = qs.model._meta
    model_str = '%s.%s' % (opts.app_label, opts.model_name)
    qs = qs.extra(select={'model': "'%s'" % model_str}).values('id', 'model', 'posted')
    return qs.query.sql_with_params()


def _group_rows(rows):
    groups = defaultdict(list)
    for model, pk in rows:
        groups[model].append(pk)
    return groups


def _get_model(full_name):
    return get_model(*full_name.split('.'))
