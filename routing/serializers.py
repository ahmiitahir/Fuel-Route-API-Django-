from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200, help_text="'City, ST', 'lat,lon' or an address inside the USA")
    finish = serializers.CharField(
        max_length=200, help_text="'City, ST', 'lat,lon' or an address inside the USA")
