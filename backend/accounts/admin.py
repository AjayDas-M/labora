from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import CollegeSettings, Department, Subject, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "roll_no", "department", "is_active")
    list_filter = ("role", "department", "is_active")
    search_fields = ("username", "first_name", "last_name", "roll_no")
    fieldsets = BaseUserAdmin.fieldsets + (("LABORA", {"fields": ("role", "department", "roll_no", "semester", "batch")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("LABORA", {"fields": ("role", "department", "roll_no")}),)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "semester", "academic_year", "department")
    filter_horizontal = ("teachers", "students")


admin.site.register(Department)


@admin.register(CollegeSettings)
class CollegeSettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        ("College Information", {
            "fields": ("college_name", "college_address", "logo"),
        }),
        ("Record Appearance", {
            "fields": ("record_title", "record_footer"),
        }),
        ("Security", {
            "fields": ("students_secure_browser_only",),
        }),
        ("Record Format Templates", {
            "description": (
                "Upload official DOCX templates here. The system fills placeholders automatically "
                "when students download records. Leave blank to use the built-in default format."
            ),
            "fields": ("record_template", "section_template", "sample_template_link"),
        }),
    ]
    readonly_fields = ("sample_template_link",)

    def sample_template_link(self, obj):
        return format_html(
            '<a class="button" href="/api/admin/sample-record-template/?type=record" '
            'style="margin-right:16px;padding:6px 12px;background:#417690;color:#fff;'
            'border-radius:4px;text-decoration:none">&#8595; Lab Record Template</a>'
            '<a class="button" href="/api/admin/sample-record-template/?type=section" '
            'style="padding:6px 12px;background:#417690;color:#fff;border-radius:4px;text-decoration:none">'
            '&#8595; Section Questions Template</a>'
        )
    sample_template_link.short_description = "Download Starter Templates"

    def has_add_permission(self, request):
        return not CollegeSettings.objects.exists()
