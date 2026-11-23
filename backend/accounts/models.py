from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Batch(models.Model):
    name = models.CharField(max_length=50, help_text="e.g. 2025-27")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="batches")
    semester = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-name", "department__name"]
        unique_together = [("name", "department")]

    def __str__(self):
        return f"{self.department.code} - {self.name} (Sem {self.semester})"


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")
    roll_no = models.CharField(max_length=40, blank=True)
    semester = models.PositiveSmallIntegerField(null=True, blank=True)
    batch = models.CharField(max_length=40, blank=True)

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    def __str__(self):
        name = self.get_full_name() or self.username
        return f"{name} ({self.role})"


class Subject(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30)
    semester = models.PositiveSmallIntegerField(default=1)
    academic_year = models.CharField(max_length=20, blank=True, help_text="e.g. 2026-27")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="subjects")
    teachers = models.ManyToManyField(User, related_name="teaching_subjects", blank=True,
                                      limit_choices_to={"role": User.Role.TEACHER})
    students = models.ManyToManyField(User, related_name="enrolled_subjects", blank=True,
                                      limit_choices_to={"role": User.Role.STUDENT})

    class Meta:
        ordering = ["semester", "code"]
        unique_together = [("code", "academic_year")]

    def __str__(self):
        return f"{self.code} - {self.name}"


class CollegeSettings(models.Model):
    """Singleton holding the lab-record template configured by the admin."""

    college_name = models.CharField(max_length=200, default="Your College Name")
    college_address = models.CharField(max_length=300, blank=True)
    logo = models.ImageField(upload_to="logo/", null=True, blank=True)
    record_title = models.CharField(max_length=120, default="LABORATORY RECORD")
    record_footer = models.CharField(max_length=200, blank=True,
                                     default="Certified bonafide record of work done by the student.")
    students_secure_browser_only = models.BooleanField(
        default=False,
        help_text="If on, students can only sign in from the LABORA Secure Browser.",
    )
    record_template = models.FileField(
        upload_to="templates/record/",
        null=True, blank=True,
        help_text=(
            "Optional DOCX template for student practical lab records. "
            "Use Jinja2 placeholders: {{ college_name }}, {{ student_name }}, {{ roll_no }}, "
            "{{ subject_code }}, {{ subject_name }}, {{ semester }}, {{ academic_year }}, "
            "{{ batch }}, {{ department }}, {{ record_title }}. "
            "For experiments use {% for entry in entries %} ... {% endfor %} with "
            "{{ entry.experiment_no }}, {{ entry.title }}, {{ entry.date }}, {{ entry.aim }}, "
            "{{ entry.language }}, {{ entry.code }}, {{ entry.stdin }}, {{ entry.output }}, "
            "{{ entry.result }}, {{ entry.approved_by }}, {{ entry.approved_on }}."
        ),
    )
    section_template = models.FileField(
        upload_to="templates/section/",
        null=True, blank=True,
        help_text=(
            "Optional DOCX template for section question downloads. "
            "Use placeholders: {{ college_name }}, {{ subject_code }}, {{ subject_name }}, "
            "{{ section_number }}, {{ section_title }}, {{ section_description }}, "
            "{{ approved_by }}, {{ approved_at }}, {{ generated_at }}. "
            "For questions use {% for q in questions %} ... {% endfor %} with "
            "{{ q.question_no }}, {{ q.text }}, {{ q.marks }}."
        ),
    )

    class Meta:
        verbose_name_plural = "College settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.college_name
