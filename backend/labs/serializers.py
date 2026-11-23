from rest_framework import serializers

from .models import ActivityEvent, CodeVersion, Execution, Practical, QuestionSection, SectionQuestion, Submission


class PracticalSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)

    class Meta:
        model = Practical
        fields = ["id", "subject", "subject_name", "subject_code", "experiment_no", "title", "aim", "question",
                  "language", "starter_code", "sample_input", "restricted", "require_secure_browser",
                  "is_published", "due_date", "created_at"]
        read_only_fields = ["created_at"]


class StudentPracticalSerializer(PracticalSerializer):
    my_status = serializers.SerializerMethodField()

    class Meta(PracticalSerializer.Meta):
        fields = PracticalSerializer.Meta.fields + ["my_status"]

    def get_my_status(self, obj):
        subs = self.context.get("my_subs", {})
        return subs.get(obj.id, "not_started")


class ExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = ["id", "stdin", "stdout", "stderr", "compile_output", "status", "time", "memory", "created_at"]


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeVersion
        fields = ["id", "number", "code", "reason", "created_at"]


class EventSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = ActivityEvent
        fields = ["id", "kind", "kind_label", "chars", "detail", "client_time", "created_at", "secure_browser"]


class SubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    roll_no = serializers.CharField(source="student.roll_no", read_only=True)
    locked = serializers.BooleanField(source="is_locked", read_only=True)

    class Meta:
        model = Submission
        fields = ["id", "practical", "student", "student_name", "roll_no", "code", "status", "locked", "result",
                  "teacher_note", "started_at", "updated_at", "submitted_at", "approved_at", "record_execution"]

    def get_student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username


# ---------------------------------------------------------------------------
# Section-wise Question serializers
# ---------------------------------------------------------------------------
class SectionQuestionSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SectionQuestion
        fields = [
            "id", "section", "question_no", "text", "marks",
            "status", "status_label", "approved_by", "approved_by_name",
            "approved_at", "rejection_reason", "created_at", "updated_at",
        ]
        read_only_fields = ["status", "approved_by", "approved_at", "created_at", "updated_at"]

    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else ""


class QuestionSectionSerializer(serializers.ModelSerializer):
    questions = SectionQuestionSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    approved_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    all_questions_approved = serializers.BooleanField(read_only=True)
    question_count = serializers.SerializerMethodField()
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)

    class Meta:
        model = QuestionSection
        fields = [
            "id", "subject", "subject_name", "subject_code",
            "section_number", "title", "description",
            "status", "status_label",
            "approved_by", "approved_by_name", "approved_at", "rejection_reason",
            "created_by", "created_by_name", "created_at", "updated_at",
            "all_questions_approved", "question_count", "questions",
        ]
        read_only_fields = ["status", "approved_by", "approved_at", "created_at", "updated_at"]

    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else ""

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else ""

    def get_question_count(self, obj):
        return obj.questions.count()
