from datetime import datetime, timedelta

from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, renderer_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from accounts.models import Subject, User
from accounts.permissions import IsStudent, IsTeacherOrAdmin

from . import records, section_records
from .ai_review import AIUnavailable, ai_enabled, summarize_submission
from .executor import ExecutorError, run_code
from .indicators import compute_indicators
from .models import ActivityEvent, ApprovalStatus, CodeVersion, Execution, Practical, QuestionSection, SectionQuestion, Submission
from .secure_browser import is_secure_browser_request
from .serializers import (EventSerializer, ExecutionSerializer, PracticalSerializer,
                          QuestionSectionSerializer, SectionQuestionSerializer,
                          StudentPracticalSerializer, SubmissionSerializer, VersionSerializer)

MAX_CODE_CHARS = 100_000
MAX_STDIN_CHARS = 20_000


class RunThrottle(UserRateThrottle):
    scope = "run"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def teacher_can_access_subject(user, subject: Subject) -> bool:
    return user.is_admin_role or subject.teachers.filter(pk=user.pk).exists()


def get_student_practical(request, practical_id) -> Practical:
    p = get_object_or_404(Practical.objects.select_related("subject"), pk=practical_id, is_published=True)
    if not p.subject.students.filter(pk=request.user.pk).exists():
        raise PermissionDenied("You are not enrolled in this subject.")
    if p.require_secure_browser and not is_secure_browser_request(request):
        raise PermissionDenied({"detail": "This practical can only be opened in the LABORA Secure Browser.",
                                "code": "secure_browser_required"})
    return p


def get_submission(request, practical) -> Submission:
    sub, created = Submission.objects.get_or_create(
        practical=practical, student=request.user, defaults={"code": practical.starter_code}
    )
    return sub


def add_version(sub: Submission, code: str, reason: str):
    last = sub.versions.order_by("-number").first()
    if last and last.code == code:
        return last
    return CodeVersion.objects.create(submission=sub, number=(last.number + 1 if last else 1), code=code,
                                      reason=reason)


def clean_code(data, key="code", limit=MAX_CODE_CHARS):
    val = data.get(key, "")
    if not isinstance(val, str):
        raise ValidationError({key: "Must be text."})
    if len(val) > limit:
        raise ValidationError({key: f"Too long (max {limit} characters)."})
    return val


def ensure_editable(sub: Submission):
    if sub.is_locked:
        raise PermissionDenied({"detail": "This practical has been submitted and is locked.", "code": "locked"})


# ---------------------------------------------------------------------------
# Practicals (teacher CRUD, student list)
# ---------------------------------------------------------------------------
class PracticalViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = Practical.objects.select_related("subject")
        subject = self.request.query_params.get("subject")
        if subject:
            qs = qs.filter(subject_id=subject)
        if u.is_admin_role:
            return qs
        if u.is_teacher:
            return qs.filter(subject__teachers=u)
        return qs.filter(subject__students=u, is_published=True)

    def get_serializer_class(self):
        return StudentPracticalSerializer if self.request.user.is_student else PracticalSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request.user.is_authenticated and self.request.user.is_student:
            ctx["my_subs"] = dict(Submission.objects.filter(student=self.request.user)
                                  .values_list("practical_id", "status"))
        return ctx

    def retrieve(self, request, *args, **kwargs):
        if request.user.is_student:
            # Students open practicals through /workspace/, which enforces secure-browser rules.
            p = self.get_object()
            data = {k: v for k, v in self.get_serializer(p).data.items()
                    if k not in ("question", "starter_code", "sample_input", "aim")}
            return Response(data)
        return super().retrieve(request, *args, **kwargs)

    def _check_write(self, subject):
        u = self.request.user
        if u.is_student or not teacher_can_access_subject(u, subject):
            raise PermissionDenied("You do not teach this subject.")

    def perform_create(self, serializer):
        self._check_write(serializer.validated_data["subject"])
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._check_write(serializer.instance.subject)
        if "subject" in serializer.validated_data:
            self._check_write(serializer.validated_data["subject"])
        serializer.save()

    def perform_destroy(self, instance):
        self._check_write(instance.subject)
        instance.delete()

    @action(detail=True, methods=["get"], permission_classes=[IsTeacherOrAdmin])
    def submissions(self, request, pk=None):
        """Teacher dashboard table (slide 10): every enrolled student with status, runs and indicators."""
        p = self.get_object()
        subs = {s.student_id: s for s in p.submissions.select_related("student")
                .prefetch_related("events", "versions").annotate(runs=Count("executions", distinct=True))}
        rows = []
        for st in p.subject.students.order_by("roll_no", "username"):
            s = subs.get(st.id)
            rows.append({
                "student_id": st.id,
                "student_name": st.get_full_name() or st.username,
                "roll_no": st.roll_no,
                "submission_id": s.id if s else None,
                "status": s.status if s else "not_started",
                "runs": s.runs if s else 0,
                "submitted_at": s.submitted_at if s else None,
                "indicators": compute_indicators(s) if s else [],
            })
        return Response({"practical": PracticalSerializer(p).data, "rows": rows})


# ---------------------------------------------------------------------------
# Student workspace (restricted environment)
# ---------------------------------------------------------------------------
def workspace_payload(request, p, sub):
    return {
        "practical": PracticalSerializer(p).data,
        "submission": SubmissionSerializer(sub).data,
        "last_execution": ExecutionSerializer(sub.executions.last()).data if sub.executions.exists() else None,
        "secure_browser": is_secure_browser_request(request),
    }


@api_view(["GET"])
@permission_classes([IsStudent])
def workspace(request, practical_id):
    p = get_student_practical(request, practical_id)
    sub = get_submission(request, p)
    recent = sub.events.filter(kind=ActivityEvent.Kind.SESSION_START,
                               created_at__gte=timezone.now() - timedelta(seconds=10)).exists()
    if not recent:  # page reloads within a few seconds count as one session start
        ActivityEvent.objects.create(submission=sub, kind=ActivityEvent.Kind.SESSION_START,
                                     secure_browser=is_secure_browser_request(request),
                                     detail={"ua": request.headers.get("User-Agent", "")[:200]})
    return Response(workspace_payload(request, p, sub))


@api_view(["POST"])
@permission_classes([IsStudent])
def workspace_save(request, practical_id):
    p = get_student_practical(request, practical_id)
    sub = get_submission(request, p)
    ensure_editable(sub)
    sub.code = clean_code(request.data)
    sub.save(update_fields=["code", "updated_at"])
    v = add_version(sub, sub.code, CodeVersion.Reason.AUTOSAVE)
    return Response({"saved_at": timezone.now(), "version": v.number})


@api_view(["POST"])
@permission_classes([IsStudent])
@throttle_classes([RunThrottle])
def workspace_run(request, practical_id):
    p = get_student_practical(request, practical_id)
    sub = get_submission(request, p)
    ensure_editable(sub)
    code = clean_code(request.data)
    stdin = clean_code(request.data, "stdin", MAX_STDIN_CHARS)
    sub.code = code
    sub.save(update_fields=["code", "updated_at"])
    add_version(sub, code, CodeVersion.Reason.RUN)
    try:
        res = run_code(p.language, code, stdin)
    except ExecutorError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    ex = Execution.objects.create(submission=sub, code=code, stdin=stdin, stdout=res.stdout[:50_000],
                                  stderr=res.stderr[:20_000], compile_output=res.compile_output[:20_000],
                                  status=res.status, time=res.time, memory=res.memory)
    ActivityEvent.objects.create(submission=sub, kind=ActivityEvent.Kind.RUN, detail={"status": res.status},
                                 secure_browser=is_secure_browser_request(request))
    return Response(ExecutionSerializer(ex).data)


ALLOWED_CLIENT_EVENTS = {
    ActivityEvent.Kind.INSERT, ActivityEvent.Kind.DELETE, ActivityEvent.Kind.INTERNAL_PASTE,
    ActivityEvent.Kind.PASTE_BLOCKED, ActivityEvent.Kind.DROP_BLOCKED, ActivityEvent.Kind.FOCUS_LOST,
    ActivityEvent.Kind.FOCUS_BACK, ActivityEvent.Kind.FULLSCREEN_EXIT, ActivityEvent.Kind.SECURE_ALERT,
}


@api_view(["POST"])
@permission_classes([IsStudent])
def workspace_events(request, practical_id):
    p = get_student_practical(request, practical_id)
    sub = get_submission(request, p)
    events = request.data.get("events", [])
    if not isinstance(events, list) or len(events) > 500:
        raise ValidationError({"events": "Send a list of at most 500 events."})
    secure = is_secure_browser_request(request)
    objs = []
    for e in events:
        if not isinstance(e, dict) or e.get("kind") not in ALLOWED_CLIENT_EVENTS:
            continue
        ct = None
        try:
            if e.get("t"):
                ct = datetime.fromtimestamp(int(e["t"]) / 1000, tz=timezone.get_current_timezone())
        except (TypeError, ValueError, OverflowError, OSError):
            ct = None
        detail = e.get("detail") if isinstance(e.get("detail"), dict) else {}
        objs.append(ActivityEvent(submission=sub, kind=e["kind"], chars=int(e.get("chars") or 0),
                                  detail={k: str(v)[:300] for k, v in list(detail.items())[:10]},
                                  client_time=ct, secure_browser=secure))
    ActivityEvent.objects.bulk_create(objs)
    return Response({"stored": len(objs)})


@api_view(["POST"])
@permission_classes([IsStudent])
def workspace_submit(request, practical_id):
    p = get_student_practical(request, practical_id)
    sub = get_submission(request, p)
    ensure_editable(sub)
    code = clean_code(request.data)
    last_ok = sub.executions.filter(status="Accepted").order_by("-created_at").first()
    if not last_ok or last_ok.code != code:
        return Response({"detail": "Run your final program successfully before submitting, so the record "
                                   "contains its real output.", "code": "run_required"}, status=400)
    sub.code = code
    sub.status = Submission.Status.SUBMITTED
    sub.submitted_at = timezone.now()
    sub.record_execution = last_ok
    sub.save()
    add_version(sub, code, CodeVersion.Reason.SUBMIT)
    ActivityEvent.objects.create(submission=sub, kind=ActivityEvent.Kind.SUBMIT,
                                 secure_browser=is_secure_browser_request(request))
    return Response(workspace_payload(request, p, sub))


# ---------------------------------------------------------------------------
# Teacher review
# ---------------------------------------------------------------------------
def get_teacher_submission(request, pk) -> Submission:
    sub = get_object_or_404(Submission.objects.select_related("practical__subject", "student"), pk=pk)
    if not teacher_can_access_subject(request.user, sub.practical.subject):
        raise PermissionDenied("You do not teach this subject.")
    return sub


@api_view(["GET"])
@permission_classes([IsTeacherOrAdmin])
def submission_detail(request, pk):
    sub = get_teacher_submission(request, pk)
    return Response({
        "submission": SubmissionSerializer(sub).data,
        "practical": PracticalSerializer(sub.practical).data,
        "versions": VersionSerializer(sub.versions.all(), many=True).data,
        "events": EventSerializer(sub.events.all(), many=True).data,
        "executions": ExecutionSerializer(sub.executions.all(), many=True).data,
        "indicators": compute_indicators(sub),
        "ai_enabled": ai_enabled(),
    })


@api_view(["POST"])
@permission_classes([IsTeacherOrAdmin])
def submission_approve(request, pk):
    sub = get_teacher_submission(request, pk)
    if sub.status != Submission.Status.SUBMITTED:
        return Response({"detail": "Only submitted work can be approved."}, status=400)
    ex_id = request.data.get("execution_id")
    if ex_id:
        sub.record_execution = get_object_or_404(Execution, pk=ex_id, submission=sub, code=sub.code)
    sub.result = str(request.data.get("result", "") or sub.result)[:2000]
    sub.teacher_note = str(request.data.get("note", "") or "")[:2000]
    sub.status = Submission.Status.APPROVED
    sub.approved_at = timezone.now()
    sub.approved_by = request.user
    sub.save()
    return Response(SubmissionSerializer(sub).data)


@api_view(["POST"])
@permission_classes([IsTeacherOrAdmin])
def submission_request_correction(request, pk):
    sub = get_teacher_submission(request, pk)
    if sub.status not in (Submission.Status.SUBMITTED, Submission.Status.APPROVED):
        return Response({"detail": "Nothing to send back."}, status=400)
    sub.status = Submission.Status.CORRECTION
    sub.teacher_note = str(request.data.get("note", ""))[:2000]
    sub.approved_at = None
    sub.approved_by = None
    sub.save()
    return Response(SubmissionSerializer(sub).data)


@api_view(["POST"])
@permission_classes([IsTeacherOrAdmin])
def submission_ai_summary(request, pk):
    sub = get_teacher_submission(request, pk)
    try:
        text = summarize_submission(sub.practical.get_language_display(), sub.practical.question, sub.code,
                                    compute_indicators(sub), sub.versions.count())
    except AIUnavailable as exc:
        return Response({"detail": str(exc)}, status=503)
    return Response({"summary": text, "note": "AI output is a review aid only, not proof."})


class PassthroughContentNegotiation(BaseContentNegotiation):
    """Allows query parameters like ?format=pdf or ?format=docx without DRF 404ing on content negotiation."""
    def select_renderer(self, request, renderers, format_suffix=None):
        return (renderers[0], renderers[0].media_type)


class PDFRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class DocxRenderer(BaseRenderer):
    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    format = "docx"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


def passthrough_conneg(view_func):
    """Decorator for DRF API views to allow ?format=pdf/docx or any format parameter without 404."""
    if hasattr(view_func, "cls"):
        view_func.cls.content_negotiation_class = PassthroughContentNegotiation
    return view_func


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
def _file_response(ctx, kind, filename):
    if kind == "docx":
        data = records.build_docx(ctx)
        ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        try:
            data = records.build_pdf(ctx)
        except Exception as exc:
            return Response({"detail": f"PDF generation error: {exc}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        ctype = "application/pdf"
        kind = "pdf"
    resp = HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{filename}.{kind}"'
    return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def record_overview(request):
    """Student: approved practicals per subject, ready for the record."""
    u = request.user
    if not u.is_student:
        return Response({"detail": "Students only."}, status=403)
    out = []
    for subj in u.enrolled_subjects.all().order_by("code"):
        subs = Submission.objects.filter(student=u, practical__subject=subj).select_related("practical")
        practicals = subj.practicals.filter(is_published=True)
        lang = practicals.values_list("language", flat=True).first() or ""
        out.append({
            "subject": {
                "id": subj.id,
                "name": subj.name,
                "code": subj.code,
                "language": lang,
            },
            "total": practicals.count(),
            "approved": [
                {
                    "submission_id": s.id,
                    "experiment_no": s.practical.experiment_no,
                    "title": s.practical.title,
                    "language": s.practical.language,
                    "approved_at": s.approved_at,
                }
                for s in subs if s.status == Submission.Status.APPROVED
            ],
        })
    return Response(out)


@passthrough_conneg
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, PDFRenderer, DocxRenderer])
def records_download(request):
    subject_id = request.query_params.get("subject_id") or request.GET.get("subject_id")
    if not subject_id:
        return Response(
            {"detail": "subject_id parameter is required.", "code": "subject_id_required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    subject = get_object_or_404(Subject, pk=subject_id)
    u = request.user
    if u.is_student:
        student = u
        if not subject.students.filter(pk=u.pk).exists():
            raise PermissionDenied("You are not enrolled in this subject.")
    else:
        if not teacher_can_access_subject(u, subject):
            raise PermissionDenied("You do not teach this subject.")
        student_id = request.query_params.get("student") or request.GET.get("student")
        if student_id:
            student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)
        else:
            return Response(
                {"detail": "student parameter is required for teachers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Strictly filter submissions belonging to this subject and student
    subs = (
        Submission.objects.filter(
            student=student,
            practical__subject=subject,
            status=Submission.Status.APPROVED,
        )
        .select_related("practical", "approved_by", "record_execution")
        .order_by("practical__experiment_no")
    )

    lang = request.query_params.get("language") or request.GET.get("language")
    if lang:
        subs = subs.filter(practical__language=lang.lower().strip())

    if not subs.exists():
        return Response(
            {"detail": f"No approved practicals found for {subject.code} · {subject.name}."},
            status=status.HTTP_404_NOT_FOUND,
        )

    ctx = records.record_context(student, subject, subs)
    fmt = (request.query_params.get("format") or request.query_params.get("type") or request.GET.get("format") or request.GET.get("type", "pdf")).lower().strip()
    name = f"LabRecord_{subject.code}_{student.roll_no or student.username}"
    if lang:
        name += f"_{lang}"
    return _file_response(ctx, fmt, name)


@passthrough_conneg
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, PDFRenderer, DocxRenderer])
def record_subject(request, subject_id):
    subject = get_object_or_404(Subject, pk=subject_id)
    u = request.user
    if u.is_student:
        student = u
        if not subject.students.filter(pk=u.pk).exists():
            raise PermissionDenied()
    else:
        if not teacher_can_access_subject(u, subject):
            raise PermissionDenied()
        student = get_object_or_404(User, pk=request.query_params.get("student"), role=User.Role.STUDENT)
    subs = (Submission.objects.filter(student=student, practical__subject=subject, status=Submission.Status.APPROVED)
            .select_related("practical", "approved_by", "record_execution").order_by("practical__experiment_no"))
    lang = request.query_params.get("language")
    if lang:
        subs = subs.filter(practical__language=lang.lower().strip())
    if not subs:
        return Response({"detail": "No approved practicals yet."}, status=404)
    ctx = records.record_context(student, subject, subs)
    name = f"LabRecord_{subject.code}_{student.roll_no or student.username}"
    fmt = request.query_params.get("format") or request.query_params.get("type", "pdf")
    return _file_response(ctx, fmt, name)


@passthrough_conneg
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, PDFRenderer, DocxRenderer])
def record_single(request, pk):
    sub = get_object_or_404(Submission.objects.select_related("practical__subject", "student"), pk=pk,
                            status=Submission.Status.APPROVED)
    u = request.user
    if u.is_student and sub.student_id != u.id:
        raise PermissionDenied()
    if not u.is_student and not teacher_can_access_subject(u, sub.practical.subject):
        raise PermissionDenied()
    ctx = records.record_context(sub.student, sub.practical.subject, [sub])
    name = f"Exp{sub.practical.experiment_no}_{sub.student.roll_no or sub.student.username}"
    return _file_response(ctx, request.query_params.get("type", "pdf"), name)


# ---------------------------------------------------------------------------
# Reports (module 10)
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsTeacherOrAdmin])
def subject_report(request, subject_id):
    subject = get_object_or_404(Subject, pk=subject_id)
    if not teacher_can_access_subject(request.user, subject):
        raise PermissionDenied()
    n_students = subject.students.count()
    rows = []
    for p in subject.practicals.all():
        counts = dict(p.submissions.values_list("status").annotate(c=Count("id")))
        flagged = sum(1 for s in p.submissions.prefetch_related("events", "versions") if compute_indicators(s))
        rows.append({"practical_id": p.id, "experiment_no": p.experiment_no, "title": p.title,
                     "language": p.language, "students": n_students,
                     "not_started": n_students - sum(counts.values()),
                     "in_progress": counts.get("in_progress", 0), "submitted": counts.get("submitted", 0),
                     "correction": counts.get("correction", 0), "approved": counts.get("approved", 0),
                     "with_indicators": flagged})
    return Response({"subject": {"id": subject.id, "name": subject.name, "code": subject.code}, "rows": rows})


# ---------------------------------------------------------------------------
# Section-wise Question Management – helpers
# ---------------------------------------------------------------------------
def _teacher_can_access_section(user, section: QuestionSection) -> bool:
    return user.is_admin_role or section.subject.teachers.filter(pk=user.pk).exists()


def _student_enrolled_in_section(user, section: QuestionSection) -> bool:
    return section.subject.students.filter(pk=user.pk).exists()


# ---------------------------------------------------------------------------
# QuestionSectionViewSet  (teacher CRUD + approve/reject actions)
# ---------------------------------------------------------------------------
class QuestionSectionViewSet(viewsets.ModelViewSet):
    """CRUD for question sections. Students get read-only access to their enrolled subjects."""
    permission_classes = [IsAuthenticated]
    serializer_class = QuestionSectionSerializer

    def get_queryset(self):
        u = self.request.user
        qs = QuestionSection.objects.select_related("subject", "created_by", "approved_by").prefetch_related("questions")
        subject = self.request.query_params.get("subject")
        if subject:
            qs = qs.filter(subject_id=subject)
        if u.is_admin_role:
            return qs
        if u.is_teacher:
            return qs.filter(subject__teachers=u)
        # students see only sections from their enrolled subjects
        return qs.filter(subject__students=u)

    def _require_teacher_access(self, section):
        u = self.request.user
        if u.is_student or not _teacher_can_access_section(u, section):
            raise PermissionDenied("You do not teach this subject.")

    def perform_create(self, serializer):
        subject = serializer.validated_data["subject"]
        u = self.request.user
        if u.is_student or not (u.is_admin_role or subject.teachers.filter(pk=u.pk).exists()):
            raise PermissionDenied("You do not teach this subject.")
        serializer.save(created_by=u)

    def perform_update(self, serializer):
        self._require_teacher_access(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_teacher_access(instance)
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[IsTeacherOrAdmin])
    def approve(self, request, pk=None):
        """Approve an entire section. All questions must already be individually approved."""
        section = self.get_object()
        self._require_teacher_access(section)
        if not section.all_questions_approved:
            return Response(
                {"detail": "All questions must be individually approved before approving the section.",
                 "code": "questions_not_all_approved"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        section.status = ApprovalStatus.APPROVED
        section.approved_by = request.user
        section.approved_at = timezone.now()
        section.rejection_reason = ""
        section.save()
        return Response(QuestionSectionSerializer(section).data)

    @action(detail=True, methods=["post"], permission_classes=[IsTeacherOrAdmin])
    def reject(self, request, pk=None):
        """Reject a section."""
        section = self.get_object()
        self._require_teacher_access(section)
        section.status = ApprovalStatus.REJECTED
        section.approved_by = None
        section.approved_at = None
        section.rejection_reason = str(request.data.get("reason", ""))[:1000]
        section.save()
        return Response(QuestionSectionSerializer(section).data)

    @action(detail=True, methods=["post"], permission_classes=[IsTeacherOrAdmin])
    def reset(self, request, pk=None):
        """Reset section status back to pending."""
        section = self.get_object()
        self._require_teacher_access(section)
        section.status = ApprovalStatus.PENDING
        section.approved_by = None
        section.approved_at = None
        section.rejection_reason = ""
        section.save()
        return Response(QuestionSectionSerializer(section).data)


# ---------------------------------------------------------------------------
# SectionQuestionViewSet  (teacher CRUD + per-question approve/reject)
# ---------------------------------------------------------------------------
class SectionQuestionViewSet(viewsets.ModelViewSet):
    """CRUD for individual questions within a section."""
    permission_classes = [IsAuthenticated]
    serializer_class = SectionQuestionSerializer

    def get_queryset(self):
        u = self.request.user
        qs = SectionQuestion.objects.select_related("section__subject", "approved_by")
        section = self.request.query_params.get("section")
        if section:
            qs = qs.filter(section_id=section)
        if u.is_admin_role:
            return qs
        if u.is_teacher:
            return qs.filter(section__subject__teachers=u)
        # Students see questions only in sections of their enrolled subjects
        return qs.filter(section__subject__students=u)

    def _get_section(self, section_id):
        return get_object_or_404(QuestionSection.objects.select_related("subject"), pk=section_id)

    def _require_teacher_access_to_section(self, section):
        u = self.request.user
        if u.is_student or not _teacher_can_access_section(u, section):
            raise PermissionDenied("You do not teach this subject.")

    def perform_create(self, serializer):
        section = serializer.validated_data["section"]
        self._require_teacher_access_to_section(section)
        serializer.save()

    def perform_update(self, serializer):
        self._require_teacher_access_to_section(serializer.instance.section)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_teacher_access_to_section(instance.section)
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[IsTeacherOrAdmin])
    def approve(self, request, pk=None):
        """Approve an individual question."""
        q = self.get_object()
        self._require_teacher_access_to_section(q.section)
        q.status = ApprovalStatus.APPROVED
        q.approved_by = request.user
        q.approved_at = timezone.now()
        q.rejection_reason = ""
        q.save()
        return Response(SectionQuestionSerializer(q).data)

    @action(detail=True, methods=["post"], permission_classes=[IsTeacherOrAdmin])
    def reject(self, request, pk=None):
        """Reject an individual question."""
        q = self.get_object()
        self._require_teacher_access_to_section(q.section)
        q.status = ApprovalStatus.REJECTED
        q.approved_by = None
        q.approved_at = None
        q.rejection_reason = str(request.data.get("reason", ""))[:1000]
        q.save()
        return Response(SectionQuestionSerializer(q).data)

    @action(detail=True, methods=["post"], permission_classes=[IsTeacherOrAdmin])
    def reset(self, request, pk=None):
        """Reset individual question status back to pending."""
        q = self.get_object()
        self._require_teacher_access_to_section(q.section)
        q.status = ApprovalStatus.PENDING
        q.approved_by = None
        q.approved_at = None
        q.rejection_reason = ""
        q.save()
        return Response(SectionQuestionSerializer(q).data)


# ---------------------------------------------------------------------------
# Download approved section questions as PDF or DOCX
# ---------------------------------------------------------------------------
@passthrough_conneg
@api_view(["GET"])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, PDFRenderer, DocxRenderer])
def download_section(request, pk):
    """Download all questions in an approved section.
    Students: must be enrolled in the section's subject AND section must be approved.
    Teachers/admins: may download any section they can access.
    """
    section = get_object_or_404(
        QuestionSection.objects.select_related("subject", "approved_by"),
        pk=pk,
    )
    u = request.user

    if u.is_student:
        # Enforce enrollment
        if not _student_enrolled_in_section(u, section):
            raise PermissionDenied("You are not enrolled in this subject.")
        # Enforce section approval
        if section.status != ApprovalStatus.APPROVED:
            raise PermissionDenied({"detail": "This section is not yet approved for download.",
                                    "code": "section_not_approved"})
    else:
        if not _teacher_can_access_section(u, section):
            raise PermissionDenied("You do not teach this subject.")

    questions = section.questions.order_by("question_no")
    kind = request.query_params.get("type", "pdf").lower()
    safe_title = section.title.replace(" ", "_")[:40]
    filename = f"Section{section.section_number}_{safe_title}_{section.subject.code}"

    if kind == "docx":
        data = section_records.build_section_docx(section, questions)
        ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        try:
            data = section_records.build_section_pdf(section, questions)
        except Exception as exc:
            return Response({"detail": f"PDF generation error: {exc}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        ctype = "application/pdf"
        kind = "pdf"

    resp = HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{filename}.{kind}"'
    return resp


# ---------------------------------------------------------------------------
# Question Portal – serve standalone HTML SPA
# ---------------------------------------------------------------------------
from django.shortcuts import render as django_render  # noqa: E402


def question_portal_view(request):
    """Serves the standalone Question Portal HTML page."""
    return django_render(request, "labs/question_portal.html")


# ---------------------------------------------------------------------------
# Admin: sample template download
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_record_template(request):
    """Download a starter DOCX template pre-filled with all available placeholders.
    Admin opens this in Word, designs the layout, keeps the placeholders, and uploads it back.
    type=record  → lab record template
    type=section → section questions template
    """
    if not request.user.is_admin_role:
        raise PermissionDenied("Admin only.")

    kind = request.query_params.get("type", "record")

    import io as _io
    from docx import Document as _Document
    from docx.shared import Pt as _Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH as _ALIGN

    doc = _Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = _Pt(12)

    if kind == "section":
        # --- Section questions starter template ---
        h = doc.add_paragraph()
        h.alignment = _ALIGN.CENTER
        h.add_run("{{ college_name }}").bold = True
        doc.add_paragraph("{{ college_address }}").alignment = _ALIGN.CENTER
        doc.add_paragraph()

        sub_p = doc.add_paragraph()
        sub_p.alignment = _ALIGN.CENTER
        sub_p.add_run("Subject: {{ subject_code }} – {{ subject_name }}").bold = True

        sec_p = doc.add_paragraph()
        sec_p.alignment = _ALIGN.CENTER
        sec_p.add_run("Section {{ section_number }}: {{ section_title }}").bold = True

        doc.add_paragraph("{{ section_description }}")
        doc.add_paragraph()

        doc.add_paragraph(
            "INSTRUCTIONS: The table below loops over all questions in this section.\n"
            "Keep the Jinja2 tags exactly as shown. Design the rows however you like."
        ).runs[0].italic = True

        tbl = doc.add_table(rows=1, cols=3)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        hdr[0].text = "Q.No"
        hdr[1].text = "Question"
        hdr[2].text = "Marks"
        for cell in hdr:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.bold = True

        loop_row = tbl.add_row().cells
        loop_row[0].text = "{% for q in questions %}{{ q.question_no }}"
        loop_row[1].text = "{{ q.text }}"
        loop_row[2].text = "{{ q.marks }}{% endfor %}"

        doc.add_paragraph()
        doc.add_paragraph(
            "Approved by: {{ approved_by }}    Date: {{ approved_at }}    Generated: {{ generated_at }}"
        )
        filename = "LABORA_Section_Template_SAMPLE"

    else:
        # --- Lab record starter template ---
        h = doc.add_paragraph()
        h.alignment = _ALIGN.CENTER
        h.add_run("{{ college_name }}").bold = True
        doc.add_paragraph("{{ college_address }}").alignment = _ALIGN.CENTER
        doc.add_paragraph()

        t = doc.add_paragraph()
        t.alignment = _ALIGN.CENTER
        t.add_run("{{ record_title }}").bold = True

        info_tbl = doc.add_table(rows=0, cols=2)
        info_tbl.style = "Table Grid"
        for label, placeholder in [
            ("Name", "{{ student_name }}"), ("Roll No", "{{ roll_no }}"),
            ("Batch", "{{ batch }}"), ("Department", "{{ department }}"),
            ("Subject", "{{ subject_code }} – {{ subject_name }}"),
            ("Semester", "{{ semester }}"), ("Academic Year", "{{ academic_year }}"),
        ]:
            row = info_tbl.add_row().cells
            row[0].text = label
            row[1].text = placeholder

        doc.add_paragraph()
        doc.add_paragraph(
            "INSTRUCTIONS: The block below loops over each approved experiment.\n"
            "Keep all Jinja2 tags exactly as shown. Design the layout however you like."
        ).runs[0].italic = True
        doc.add_paragraph()

        # Loop markers
        doc.add_paragraph("{% for entry in entries %}")
        p = doc.add_paragraph()
        p.add_run("Experiment No: {{ entry.experiment_no }}").bold = True
        p.add_run("          Date: {{ entry.date }}")
        doc.add_paragraph("Title: {{ entry.title }}")
        doc.add_paragraph("Aim: {{ entry.aim }}")
        doc.add_paragraph("Language: {{ entry.language }}")
        doc.add_paragraph("Source Code:\n{{ entry.code }}")
        doc.add_paragraph("Input:\n{{ entry.stdin }}")
        doc.add_paragraph("Output:\n{{ entry.output }}")
        doc.add_paragraph("Result: {{ entry.result }}")
        doc.add_paragraph("Approved by: {{ entry.approved_by }}    Date: {{ entry.approved_on }}")
        doc.add_paragraph("{% endfor %}")
        filename = "LABORA_LabRecord_Template_SAMPLE"

    buf = _io.BytesIO()
    doc.save(buf)
    ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    resp = HttpResponse(buf.getvalue(), content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{filename}.docx"'
    return resp
