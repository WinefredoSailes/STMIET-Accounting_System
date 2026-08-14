from rest_framework import viewsets

from .models import ApprovalRequest
from .serializers import ApprovalRequestSerializer


class ApprovalRequestViewSet(viewsets.ModelViewSet):
    queryset = ApprovalRequest.objects.prefetch_related("actions")
    serializer_class = ApprovalRequestSerializer