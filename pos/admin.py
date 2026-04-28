from django.contrib import admin
from .models import Sale, SaleItem, SalePayment, POSSetting

admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(SalePayment)
admin.site.register(POSSetting)