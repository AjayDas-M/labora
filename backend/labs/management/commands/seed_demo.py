from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Batch, CollegeSettings, Department, Subject, User
from labs.models import ApprovalStatus, Execution, Practical, QuestionSection, SectionQuestion, Submission

SUBJECT_DEFS = [
    {
        "code": "MCA101",
        "name": "C Programming Lab",
        "language": "c",
        "practicals": [
            {
                "experiment_no": 1,
                "title": "Sum of N Numbers",
                "aim": "To write a C program to find the sum of N numbers entered by the user.",
                "question": "Write a C program that reads N and then N integers, and prints their sum.",
                "starter_code": "#include <stdio.h>\n\nint main() {\n    // write your program here\n    return 0;\n}\n",
                "sample_input": "5\n1 2 3 4 5\n",
                "code": '#include <stdio.h>\nint main() {\n    int n, i, val, sum = 0;\n    if (scanf("%d", &n) != 1) return 0;\n    for (i = 0; i < n; i++) {\n        scanf("%d", &val);\n        sum += val;\n    }\n    printf("%d\\n", sum);\n    return 0;\n}\n',
                "stdin": "5\n1 2 3 4 5\n",
                "stdout": "15\n",
                "auto_approve": True,
            },
            {
                "experiment_no": 2,
                "title": "Matrix Operations & Transpose",
                "aim": "To write a C program to compute the transpose of an M x N matrix.",
                "question": "Write a program that takes rows M, columns N, reads an M x N matrix and outputs its transpose.",
                "starter_code": "#include <stdio.h>\n\nint main() {\n    // matrix transpose\n    return 0;\n}\n",
                "sample_input": "2 3\n1 2 3\n4 5 6\n",
                "code": "",
                "stdin": "",
                "stdout": "",
                "auto_approve": False,
            },
        ],
        "sections": [
            {
                "number": 1,
                "title": "C Fundamentals & I/O Operations",
                "desc": "Basic syntax, variables, operators, and formatted I/O operations.",
                "status": ApprovalStatus.APPROVED,
                "questions": [
                    (1, "Write a C program to calculate the area and circumference of a circle given its radius.", 5, ApprovalStatus.APPROVED, ""),
                    (2, "Demonstrate fundamental data types (int, float, char, double) and their sizes using sizeof operator.", 5, ApprovalStatus.APPROVED, ""),
                    (3, "Write a C program to swap two numbers using a temporary variable and without using a temporary variable.", 5, ApprovalStatus.APPROVED, ""),
                    (4, "Explain bitwise operators in C (&, |, ^, ~, <<, >>) with a code example showing bit manipulation.", 10, ApprovalStatus.APPROVED, ""),
                    (5, "Write a C program that converts temperature from Celsius to Fahrenheit and vice versa based on user selection.", 5, ApprovalStatus.APPROVED, ""),
                ],
            },
            {
                "number": 2,
                "title": "Control Structures & Looping",
                "desc": "Conditional statements, switch-case, and iterative structures.",
                "status": ApprovalStatus.PENDING,
                "questions": [
                    (1, "Write a C program to find the largest among three numbers using nested if-else statements.", 5, ApprovalStatus.APPROVED, ""),
                    (2, "Implement a simple menu-driven calculator using switch-case supporting +, -, *, /, and % operations.", 10, ApprovalStatus.APPROVED, ""),
                    (3, "Write a C program to check whether a given integer is a palindrome number.", 5, ApprovalStatus.APPROVED, ""),
                    (4, "Write a C program to print Pascal's triangle up to N rows using nested loops.", 10, ApprovalStatus.PENDING, ""),
                ],
            },
            {
                "number": 3,
                "title": "Pointers, Arrays & Functions",
                "desc": "Modular programming, call by value vs reference, and recursive problem solving.",
                "status": ApprovalStatus.REJECTED,
                "rejection_reason": "Question 2 needs revised marks allocation and updated problem statement.",
                "questions": [
                    (1, "Write a recursive function to compute the Nth Fibonacci number and analyze its time complexity.", 10, ApprovalStatus.APPROVED, ""),
                    (2, "Demonstrate pointer arithmetic and passing arrays to functions using pointers.", 5, ApprovalStatus.REJECTED, "Clarify the expected output format and edge cases."),
                    (3, "Write a function to compute GCD of two numbers using the Euclidean algorithm.", 5, ApprovalStatus.APPROVED, ""),
                ],
            },
        ],
    },
    {
        "code": "MCA102",
        "name": "Java Programming Lab",
        "language": "java",
        "practicals": [
            {
                "experiment_no": 1,
                "title": "Factorial using Recursion",
                "aim": "To write a Java program to find the factorial of a number using recursion.",
                "question": "Write a Java program that reads a number and prints its factorial using a recursive method. The class must be named Main.",
                "starter_code": "import java.util.Scanner;\n\npublic class Main {\n    public static void main(String[] args) {\n        // write your program here\n    }\n}\n",
                "sample_input": "5\n",
                "code": "import java.util.Scanner;\n\npublic class Main {\n    static long fact(int n) {\n        if (n <= 1) return 1;\n        return n * fact(n - 1);\n    }\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        int n = sc.hasNextInt() ? sc.nextInt() : 5;\n        System.out.println(fact(n));\n    }\n}\n",
                "stdin": "5\n",
                "stdout": "120\n",
                "auto_approve": True,
            },
            {
                "experiment_no": 2,
                "title": "Inheritance and Method Overriding",
                "aim": "To demonstrate single and multilevel inheritance with method overriding in Java.",
                "question": "Create a base class Person and derived classes Student and GraduateStudent showing method overriding.",
                "starter_code": "public class Main {\n    public static void main(String[] args) {\n        // write your program here\n    }\n}\n",
                "sample_input": "",
                "code": "",
                "stdin": "",
                "stdout": "",
                "auto_approve": False,
            },
        ],
        "sections": [
            {
                "number": 1,
                "title": "Java Object-Oriented Fundamentals",
                "desc": "Classes, constructors, static members, and packages in Java.",
                "status": ApprovalStatus.APPROVED,
                "questions": [
                    (1, "Explain class and object concepts in Java with an example demonstrating instance variables and methods.", 5, ApprovalStatus.APPROVED, ""),
                    (2, "Demonstrate constructor overloading and the use of 'this' keyword.", 5, ApprovalStatus.APPROVED, ""),
                    (3, "Write a Java program showing interface implementation and runtime polymorphism.", 10, ApprovalStatus.APPROVED, ""),
                ],
            },
        ],
    },
    {
        "code": "MCA103",
        "name": "Python Programming Lab",
        "language": "python",
        "practicals": [
            {
                "experiment_no": 1,
                "title": "Prime Number Check",
                "aim": "To write a Python program to check whether a number is prime.",
                "question": "Write a program to check whether a number is prime.",
                "starter_code": 'n = int(input("Enter a number: "))\n# write your program here\n',
                "sample_input": "7\n",
                "code": 'n = int(input())\nif n < 2:\n    print("Not Prime")\nelse:\n    is_p = all(n % i != 0 for i in range(2, int(n**0.5) + 1))\n    print("Prime" if is_p else "Not Prime")\n',
                "stdin": "7\n",
                "stdout": "Prime\n",
                "auto_approve": True,
            },
            {
                "experiment_no": 2,
                "title": "File Processing and Word Count",
                "aim": "To write a Python program to read text and compute word frequency distribution.",
                "question": "Write a program that takes multiline text and outputs word frequency sorted by count descending.",
                "starter_code": "# write your program here\n",
                "sample_input": "hello world hello python\n",
                "code": "",
                "stdin": "",
                "stdout": "",
                "auto_approve": False,
            },
        ],
        "sections": [
            {
                "number": 1,
                "title": "Python Essentials & Data Structures",
                "desc": "Lists, tuples, dictionaries, comprehensions, and built-in functions.",
                "status": ApprovalStatus.APPROVED,
                "questions": [
                    (1, "Explain dictionary comprehension and list comprehension in Python with code examples.", 5, ApprovalStatus.APPROVED, ""),
                    (2, "Write a Python program to sort a list of tuples by the second element using a lambda function.", 5, ApprovalStatus.APPROVED, ""),
                    (3, "Demonstrate exception handling using try, except, else, and finally blocks in Python.", 10, ApprovalStatus.APPROVED, ""),
                ],
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Seed demo data with separate language subjects: MCA101 (C), MCA102 (Java), MCA103 (Python)."

    def add_arguments(self, parser):
        parser.add_argument("--secure", action="store_true",
                            help="Require the LABORA Secure Browser for all demo practicals.")
        parser.add_argument("--secure-langs", default="",
                            help="Comma-separated languages whose practicals require Secure Browser, e.g. c,java")

    def handle(self, *args, secure=False, secure_langs="", **opts):
        secure_set = {x.strip() for x in secure_langs.split(",") if x.strip()}
        cs = CollegeSettings.load()
        if cs.college_name == "Your College Name":
            cs.college_name = "Demo College of Engineering"
            cs.college_address = "Kerala, India"
            cs.save()

        dept, _ = Department.objects.get_or_create(code="MCA", defaults={"name": "Computer Applications"})
        Batch.objects.get_or_create(name="2025-27", department=dept, defaults={"semester": 1})

        def mk(username, role, pw, **extra):
            u, created = User.objects.get_or_create(username=username, defaults={"role": role, "department": dept, **extra})
            if created:
                u.set_password(pw)
                if role == User.Role.ADMIN:
                    u.is_staff = u.is_superuser = True
                u.save()
            return u

        mk("admin", User.Role.ADMIN, "admin123", first_name="Lab", last_name="Admin")
        teacher = mk("teacher", User.Role.TEACHER, "teacher123", first_name="Anitha", last_name="R")
        students = [
            mk(f"student{i}", User.Role.STUDENT, "student123", first_name="Student", last_name=chr(64 + i),
               roll_no=f"MCA{i:03d}", batch="2025-27", semester=1)
            for i in range(1, 5)
        ]
        primary_student = students[0]

        now = timezone.now()

        for s_def in SUBJECT_DEFS:
            subj, _ = Subject.objects.update_or_create(
                code=s_def["code"], academic_year="2026-27",
                defaults={"name": s_def["name"], "semester": 1, "department": dept}
            )
            subj.teachers.add(teacher)
            subj.students.add(*students)

            # Clean up practicals and sections that are not part of current definition
            valid_exp_nos = [p_def["experiment_no"] for p_def in s_def["practicals"]]
            subj.practicals.exclude(experiment_no__in=valid_exp_nos).delete()
            valid_sec_nos = [sec_def["number"] for sec_def in s_def.get("sections", [])]
            subj.question_sections.exclude(section_number__in=valid_sec_nos).delete()

            for p_def in s_def["practicals"]:
                prac, _ = Practical.objects.update_or_create(
                    subject=subj, experiment_no=p_def["experiment_no"],
                    defaults={
                        "title": p_def["title"],
                        "aim": p_def["aim"],
                        "question": p_def["question"],
                        "language": s_def["language"],
                        "starter_code": p_def["starter_code"],
                        "sample_input": p_def["sample_input"],
                        "restricted": True,
                        "require_secure_browser": secure or s_def["language"] in secure_set,
                        "created_by": teacher,
                    }
                )

                if p_def.get("auto_approve"):
                    sub, _ = Submission.objects.update_or_create(
                        practical=prac, student=primary_student,
                        defaults={
                            "code": p_def["code"],
                            "status": Submission.Status.APPROVED,
                            "result": "The program was executed successfully and the output was verified.",
                            "teacher_note": "Excellent work. Verified output.",
                            "submitted_at": now,
                            "approved_at": now,
                            "approved_by": teacher,
                        }
                    )
                    ex, _ = Execution.objects.update_or_create(
                        submission=sub,
                        defaults={
                            "code": p_def["code"],
                            "stdin": p_def["stdin"],
                            "stdout": p_def["stdout"],
                            "status": "Accepted",
                            "time": "0.02",
                        }
                    )
                    sub.record_execution = ex
                    sub.save(update_fields=["record_execution"])
                else:
                    Submission.objects.filter(practical=prac, student=primary_student).delete()

            # Sections
            for sec_def in s_def.get("sections", []):
                sec, _ = QuestionSection.objects.update_or_create(
                    subject=subj, section_number=sec_def["number"],
                    defaults={
                        "title": sec_def["title"],
                        "description": sec_def["desc"],
                        "created_by": teacher,
                        "status": sec_def["status"],
                        "approved_by": teacher if sec_def["status"] == ApprovalStatus.APPROVED else None,
                        "approved_at": now if sec_def["status"] == ApprovalStatus.APPROVED else None,
                        "rejection_reason": sec_def.get("rejection_reason", ""),
                    }
                )
                for q_item in sec_def.get("questions", []):
                    q_no, text, marks, q_status, reason = q_item
                    SectionQuestion.objects.update_or_create(
                        section=sec, question_no=q_no,
                        defaults={
                            "text": text,
                            "marks": marks,
                            "status": q_status,
                            "approved_by": teacher if q_status == ApprovalStatus.APPROVED else None,
                            "approved_at": now if q_status == ApprovalStatus.APPROVED else None,
                            "rejection_reason": reason,
                        }
                    )

        self.stdout.write(self.style.SUCCESS(
            "Demo data ready. Distinct subjects created: MCA101 (C), MCA102 (Java), MCA103 (Python)."
        ))
