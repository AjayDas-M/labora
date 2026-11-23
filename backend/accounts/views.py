import csv
import io

from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from labs.secure_browser import is_secure_browser_request

from .models import Batch, CollegeSettings, Department, Subject, User
from .permissions import IsAdminRole, ReadOnlyOrAdmin
from .serializers import (BatchSerializer, CollegeSettingsSerializer, DepartmentSerializer, MeSerializer, SubjectSerializer,
                          UserSerializer)


class LoginThrottle(AnonRateThrottle):
    rate = "20/min"


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    user = authenticate(username=request.data.get("username", ""), password=request.data.get("password", ""))
    if user is None or not user.is_active:
        return Response({"detail": "Invalid username or password."}, status=status.HTTP_401_UNAUTHORIZED)
    if user.is_student and CollegeSettings.load().students_secure_browser_only and not is_secure_browser_request(request):
        return Response({"detail": "Students must sign in from the LABORA Secure Browser.",
                         "code": "secure_browser_required"}, status=status.HTTP_403_FORBIDDEN)
    refresh = RefreshToken.for_user(user)
    return Response({"access": str(refresh.access_token), "refresh": str(refresh),
                     "user": MeSerializer(user).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(MeSerializer(request.user).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def client_status(request):
    """Lets the UI show whether the server recognised the secure browser."""
    return Response({"secure_browser": is_secure_browser_request(request),
                     "college_name": CollegeSettings.load().college_name})


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [ReadOnlyOrAdmin]


class BatchViewSet(viewsets.ModelViewSet):
    serializer_class = BatchSerializer
    permission_classes = [ReadOnlyOrAdmin]

    def get_queryset(self):
        # Auto-populate batches from existing student records if not present
        existing = set(Batch.objects.values_list("name", "department_id"))
        student_combos = (
            User.objects.filter(role=User.Role.STUDENT, department__isnull=False)
            .exclude(batch="")
            .values("batch", "department_id", "semester")
            .distinct()
        )
        to_create = []
        for c in student_combos:
            if (c["batch"], c["department_id"]) not in existing:
                to_create.append(
                    Batch(name=c["batch"], department_id=c["department_id"], semester=c["semester"] or 1)
                )
                existing.add((c["batch"], c["department_id"]))
        if to_create:
            Batch.objects.bulk_create(to_create, ignore_conflicts=True)
        return Batch.objects.select_related("department").all()


class SubjectViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectSerializer
    permission_classes = [ReadOnlyOrAdmin]

    def get_queryset(self):
        u = self.request.user
        qs = Subject.objects.select_related("department").prefetch_related("teachers", "students")
        if u.is_admin_role:
            return qs
        if u.is_teacher:
            return qs.filter(teachers=u)
        return qs.filter(students=u)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole])
    def enroll(self, request, pk=None):
        """Enroll students by username or roll number: {"students": ["21MCA01", ...]}"""
        subject = self.get_object()
        ids = [s.strip() for s in request.data.get("students", []) if str(s).strip()]
        found = list(User.objects.filter(role=User.Role.STUDENT).filter(username__in=ids)) + \
            list(User.objects.filter(role=User.Role.STUDENT, roll_no__in=ids))
        subject.students.add(*found)
        matched = {u.username for u in found} | {u.roll_no for u in found}
        return Response({"enrolled": len(set(found)), "not_found": [i for i in ids if i not in matched]})


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = User.objects.select_related("department").order_by("role", "roll_no", "username")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        batch = self.request.query_params.get("batch")
        if batch:
            qs = qs.filter(batch=batch)
        dept = self.request.query_params.get("department")
        if dept:
            qs = qs.filter(department_id=dept)
        sem = self.request.query_params.get("semester")
        if sem:
            qs = qs.filter(semester=sem)
        return qs

    @action(detail=False, methods=["post"], url_path="import")
    def import_csv(self, request):
        """CSV columns: username,password,first_name,last_name,role,roll_no,batch,semester,department_code"""
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "Upload a CSV file as 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        # Batch-scoped defaults if provided
        default_batch = (request.data.get("batch") or request.query_params.get("batch") or "").strip()
        default_sem = (request.data.get("semester") or request.query_params.get("semester") or "").strip()
        default_dept_id = (request.data.get("department") or request.query_params.get("department") or "").strip()
        default_dept = None
        if default_dept_id:
            try:
                default_dept = Department.objects.get(pk=default_dept_id)
            except (Department.DoesNotExist, ValueError):
                pass

        # 1. Check File Extension First
        fname = (f.name or "").lower()
        if fname.endswith(".xlsx") or fname.endswith(".xls"):
            return Response(
                {"detail": "Invalid file format. Please save your spreadsheet as a .csv file (CSV UTF-8) before importing."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not fname.endswith(".csv"):
            return Response(
                {"detail": "Please upload a valid .csv file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Support Multiple Encodings Gracefully
        raw = f.read()
        text = None
        for enc in ["utf-8-sig", "cp1252", "latin-1"]:
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            return Response(
                {"detail": "Unable to decode the file. Please ensure the CSV is encoded in UTF-8 or Windows-1252."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Clean Error Reporting & Robust Row Parsing
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return Response({"detail": "The CSV file is empty or missing headers."}, status=status.HTTP_400_BAD_REQUEST)

        clean_fieldnames = [(k or "").strip() for k in reader.fieldnames]
        if "username" not in clean_fieldnames:
            return Response(
                {"detail": "CSV is missing the required 'username' column header. Expected columns: username, password, first_name, last_name, role, roll_no, batch, semester, department_code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        depts = {d.code.upper(): d for d in Department.objects.all()}
        depts_by_name = {d.name.lower(): d for d in Department.objects.all()}

        created, errors = 0, []
        with transaction.atomic():
            for i, raw_row in enumerate(reader, start=2):
                if not raw_row:
                    continue
                row = {(k.strip() if k else ""): (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items() if k is not None}
                uname = row.get("username", "")
                if not uname:
                    errors.append(f"Row {i}: missing username")
                    continue
                if User.objects.filter(username=uname).exists():
                    errors.append(f"Row {i}: {uname} already exists")
                    continue

                role_val = (row.get("role") or "").lower() or User.Role.STUDENT
                if role_val not in [User.Role.STUDENT, User.Role.TEACHER, User.Role.ADMIN]:
                    role_val = User.Role.STUDENT

                dept_code = row.get("department_code", "").upper()
                dept = depts.get(dept_code) or depts_by_name.get(row.get("department_code", "").lower()) or default_dept

                batch_val = row.get("batch", "") or default_batch
                sem_str = row.get("semester", "") or default_sem
                sem_val = int(sem_str) if sem_str.isdigit() else None

                u = User(
                    username=uname,
                    first_name=row.get("first_name", ""),
                    last_name=row.get("last_name", ""),
                    role=role_val,
                    roll_no=row.get("roll_no", ""),
                    batch=batch_val,
                    department=dept,
                    semester=sem_val,
                )
                u.set_password(row.get("password") or uname)
                u.save()
                created += 1

        return Response({"created": created, "errors": errors})


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def college_settings(request):
    cs = CollegeSettings.load()
    if request.method == "GET":
        return Response(CollegeSettingsSerializer(cs).data)
    if not request.user.is_admin_role:
        return Response({"detail": "Admin only."}, status=403)
    ser = CollegeSettingsSerializer(cs, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)
