"""The single read-only endpoint.

One APIView, not a ViewSet or router: there is exactly one read-only resource
here, and routing machinery would be more scaffolding than the resource needs.
"""

from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import APODSerializer
from .services import get_apod_for_date, parse_date_param


class APODDetailView(APIView):
    """Astronomy Picture of the Day, enriched with supplemental context.

    GET /api/apod/?date=YYYY-MM-DD

    `date` is optional and defaults to today. A stored date is served straight
    from the database; anything else is fetched from NASA, persisted, and then
    served through the same serializer.
    """

    def get(self, request):
        date = parse_date_param(request.query_params.get("date"))
        apod = get_apod_for_date(date)
        return Response(APODSerializer(apod).data)
