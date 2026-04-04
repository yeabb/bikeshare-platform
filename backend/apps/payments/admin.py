from django.contrib import admin

from apps.payments.models import PricingPlan, TopUp, Transaction, Wallet


@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ("unlock_fee", "per_minute_rate", "minimum_balance", "currency", "is_active", "effective_from")
    list_filter = ("is_active", "currency")
    ordering = ("-effective_from",)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "created_at")
    search_fields = ("user__phone",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("wallet", "type", "amount", "balance_after", "reference", "created_at")
    list_filter = ("type",)
    search_fields = ("wallet__user__phone", "reference")
    readonly_fields = ("created_at",)


@admin.register(TopUp)
class TopUpAdmin(admin.ModelAdmin):
    list_display = ("wallet", "amount", "method", "status", "external_reference", "created_at")
    list_filter = ("method", "status")
    search_fields = ("wallet__user__phone", "external_reference")
    readonly_fields = ("created_at", "updated_at")
