from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import JournalEntry, PostingRule
from .serializers import JournalEntrySerializer, PostEntrySerializer, PostingRuleSerializer


class JournalEntryViewSet(
    viewsets.mixins.CreateModelMixin,
    viewsets.mixins.RetrieveModelMixin,
    viewsets.mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Draft journal entries; POST /entries/{id}/post to run the engine."""

    queryset = JournalEntry.objects.select_related("company", "segment").prefetch_related("lines")
    serializer_class = JournalEntrySerializer
    search_fields = ["entry_no", "source_doc_no", "description"]

    def get_queryset(self):
        return self.queryset

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        entry = self.get_object()
        serializer = PostEntrySerializer(
            data={"entry": entry.id, **request.data},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        posted = serializer.save()
        out = JournalEntrySerializer(posted, context={"request": request})
        return Response(out.data, status=status.HTTP_200_OK)


class PostingRuleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PostingRule.objects.filter(is_active=True).prefetch_related("lines")
    serializer_class = PostingRuleSerializer
    filterset_fields = ["event", "is_active"]
    search_fields = ["code", "name"]