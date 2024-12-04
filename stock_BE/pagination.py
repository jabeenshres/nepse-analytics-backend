import math

import logging
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


renderer_types = ['application/xlsx', ]

logger = logging.getLogger('fgv_logger')

class LargeResultsSetPagination(PageNumberPagination):
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 10000


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200
    extra_pagination_data = None
    custom_page_size = None

    def get_page_size(self, request):
        accept_type = request.headers.get('Accept', 'application/json')
        if accept_type in renderer_types:
            return None
        elif 'page_size' in request.query_params:
            page_size = int(request.query_params.get('page_size', 100))
            return page_size
        # elif self.custom_page_size:
        #     page_size = self.custom_page_size
        #     self.custom_page_size = None
        #     return page_size
        else:
            return self.page_size

    def get_paginated_response(self, data):
        status = 200
        try:
            first_row = data[0]
            if "status_code" in first_row:
                status = first_row['status_code']
                data.remove(first_row)
        except Exception as e:
            pass
        if self.extra_pagination_data:
            total_pages = None
            page_size = 1
            if "type" in self.extra_pagination_data:
                total_pages = math.ceil(len(data) / self.custom_page_size)
                i = 1
                for d in data:
                    if i % self.custom_page_size == 0:
                        d['page'] = page_size
                        page_size += 1
                    else:
                        d['page'] = page_size
                    i += 1
                del self.extra_pagination_data["type"]
            return Response({
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "total_pages": total_pages if total_pages else self.page.paginator.num_pages,
                "extra": self.extra_pagination_data,
                "results": data,
            }, status=status)
        return Response({
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "total_pages": self.page.paginator.num_pages,
            "results": data,
        }, status=status)
