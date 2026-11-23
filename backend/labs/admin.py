from django.contrib import admin

from .models import ActivityEvent, CodeVersion, Execution, Practical, QuestionSection, SectionQuestion, Submission


@admin.register(Practical)
class PracticalAdmin(admin.ModelAdmin):
    list_display = ("subject", "experiment_no", "title", "language", "restricted", "require_secure_browser", "is_published")
    list_filter = ("subject", "language")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("practical", "student", "status", "submitted_at", "approved_at")
    list_filter = ("status", "practical__subject")


admin.site.register(CodeVersion)
admin.site.register(ActivityEvent)
admin.site.register(Execution)


@admin.register(QuestionSection)
class QuestionSectionAdmin(admin.ModelAdmin):
    list_display = ("subject", "section_number", "title", "status", "created_by", "approved_by", "created_at")
    list_filter = ("status", "subject")
    search_fields = ("title", "subject__code", "subject__name")


@admin.register(SectionQuestion)
class SectionQuestionAdmin(admin.ModelAdmin):
    list_display = ("section", "question_no", "marks", "status", "approved_by")
    list_filter = ("status", "section__subject")
    search_fields = ("text",)
