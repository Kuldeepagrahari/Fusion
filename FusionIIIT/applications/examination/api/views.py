from django.db.models.query_utils import Q
from django.http import request,HttpResponse
from django.shortcuts import get_object_or_404, render, HttpResponse,redirect
from django.http import HttpResponse, HttpResponseRedirect
import itertools
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse

# from applications.academic_information.models import Student
from applications.globals.models import (DepartmentInfo, Designation,
                                         ExtraInfo, Faculty, HoldsDesignation)

from applications.academic_procedures.models import(course_registration , Register)
# from applications.academic_information.models import Course , Curriculum
from applications.programme_curriculum.models import Course as Courses , Curriculum
from applications.examination.models import(hidden_grades , authentication , grade)
from applications.department.models import(Announcements , SpecialRequest)
from applications.academic_information.models import(Student)
from applications.online_cms.models import(Student_grades)
from applications.globals.models import(ExtraInfo)
from . import serializers
from datetime import date 
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response

from django.core.serializers import serialize
from django.http import JsonResponse
import json
from datetime import datetime
import csv
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from django.db.models import IntegerField
from django.db.models.functions import Cast
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import reverse





@api_view(['POST'])
@permission_classes([IsAuthenticated])
def exam_view(request):
    """
    API to differentiate roles and provide appropriate redirection links.
    """
    role = request.data.get('Role')

    if not role:
        return Response({"error": "Role parameter is required."}, status=status.HTTP_400_BAD_REQUEST)

    if role in ["Associate Professor", "Professor", "Assistant Professor"]:
        return Response({"redirect_url": "/examination/submitGradesProf/"})
    elif role == "acadadmin":
        return Response({"redirect_url": "/examination/updateGrades/"})
    elif role == "Dean Academic":
        return Response({"redirect_url": "/examination/verifyGradesDean/"})
    else:
        return Response({"redirect_url": "/dashboard/"})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def download_template(request):
    """
    API to download a CSV template for a course based on the provided role, course, and year.
    """
    role = request.data.get('Role')
    course = request.data.get('course')
    year = request.data.get('year')

    if not role:
        return Response({"error": "Role parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not course or not year:
        return Response({"error": "Course and year are required."}, status=status.HTTP_400_BAD_REQUEST)

    if role not in ["acadadmin", "Associate Professor", "Professor", "Assistant Professor", "Dean Academic"]:
        return Response({"error": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

    try:
        User = get_user_model()
        
        course_info = course_registration.objects.filter(
            course_id_id=course,
            working_year=year
        )

        if not course_info.exists():
            return Response({"error": "No registration data found for the provided course and year"}, status=status.HTTP_404_NOT_FOUND)

        course_obj = course_info.first().course_id
        response = HttpResponse(content_type="text/csv")
        filename = f"{course_obj.code}_template_{year}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)

        writer.writerow(["roll_no", "name", "grade", "remarks"])

        for entry in course_info:
            student_entry = entry.student_id
            student_user = User.objects.get(username=student_entry.id_id)
            writer.writerow([student_entry.id_id, f"{student_user.first_name} {student_user.last_name}", "", ""])

        return response

    except Exception as e:
        print(f"Error in download_template: {str(e)}")
        return Response({'error': 'An unexpected error occurred'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

class SubmitGradesView(APIView):
    """
    API to retrieve course information for a specific academic year
    or available working years for the dropdown.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        designation = request.data.get("Role")
        academic_year = request.data.get("academic_year")

        
        if designation != "acadadmin":
            return Response(
                {"success": False, "error": "Access denied."},
                status=status.HTTP_403_FORBIDDEN
            )

       
        if academic_year:
            if not str(academic_year).isdigit():
                return Response(
                    {"error": "Invalid academic year. It must be numeric."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Fetch unique course IDs for the given academic year
            unique_course_ids = course_registration.objects.filter(
                working_year=academic_year
            ).values("course_id").distinct()

            unique_course_ids = unique_course_ids.annotate(
                course_id_int=Cast("course_id", IntegerField())
            )

            # Retrieve course information
            courses_info = Courses.objects.filter(
                id__in=unique_course_ids.values_list("course_id_int", flat=True)
            ).order_by('code')

            
            return Response(
                {"courses": list(courses_info.values())},
                status=status.HTTP_200_OK
            )

        # If no academic year is provided, return available working years
        working_years = course_registration.objects.values("working_year").distinct()

        return Response(
            {"working_years": list(working_years)},
            status=status.HTTP_200_OK
        )
    


"""
API to upload student grades via a CSV file.

- Only users with the role of 'acadadmin' can access this endpoint.
- Requires 'course_id' and 'academic_year' as form data.
- Accepts a CSV file with columns: roll_no, grade, remarks, (optional) semester.
- Validates course existence and prevents duplicate grade submissions.
- Saves grades into the 'Student_grades' model.
- Redirects based on user role after successful upload.

Expected Request:
Headers:
    Authorization: Token <your_auth_token>

Form Data:
    Role: acadadmin
    course_id: <Course_ID>
    academic_year: <Academic_Year>
    csv_file: <CSV_File>

Response:
    200 OK - {"message": "Grades uploaded successfully.", "redirect_url": "/examination/submitGrades"}
    403 Forbidden - {"error": "Access denied."}
    400 Bad Request - {"error": "Invalid file format."} or other validation errors.
    500 Internal Server Error - {"error": "An error occurred: <error_message>"}
"""

class UploadGradesAPI(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        
        des = request.data.get("Role")
        if des != "acadadmin":
            return Response(
                {"success": False, "error": "Access denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            return Response(
                {"error": "No file provided. Please upload a CSV file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not csv_file.name.endswith(".csv"):
            return Response(
                {"error": "Invalid file format. Please upload a CSV file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract course_id and academic_year from the request data
        course_id = request.data.get("course_id")
        academic_year = request.data.get("academic_year")

        if not course_id or not academic_year or not academic_year.isdigit():
            return Response(
                {"error": "Course ID and a valid Academic Year are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Fetch course and check existing grades
            courses_info = Courses.objects.get(id=course_id)
            courses = Student_grades.objects.filter(
                course_id=courses_info.id, year=academic_year
            )
            students = course_registration.objects.filter(
                course_id_id=course_id, working_year=academic_year
            )

            if not students.exists():
                message = "NO STUDENTS REGISTERED IN THIS COURSE THIS SEMESTER"
                redirect_url = reverse("examination:message") + f"?message={message}"
                return Response(
                    {"error": message, "redirect_url": redirect_url},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if courses.exists():
                message = "THIS Course was Already Submitted"
                redirect_url = reverse("examination:message") + f"?message={message}"
                return Response(
                    {"error": message, "redirect_url": redirect_url},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Parse CSV file
            decoded_file = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded_file)

            required_columns = ["roll_no", "grade", "remarks"]
            if not all(column in reader.fieldnames for column in required_columns):
                return Response(
                    {
                        "error": "CSV file must contain the following columns: roll_no, grade, remarks."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            for row in reader:
                roll_no = row["roll_no"]
                grade = row["grade"]
                remarks = row.get("remarks", "")
                semester = row.get("semester", None)

                try:
                    # Fetch student details
                    stud = Student.objects.get(id_id=roll_no)
                    semester = semester or stud.curr_semester_no
                    batch = stud.batch

                    # Create grade entry
                    Student_grades.objects.create(
                        roll_no=roll_no,
                        grade=grade,
                        remarks=remarks,
                        course_id_id=course_id,
                        year=academic_year,
                        semester=semester,
                        batch=batch,
                    )
                except Student.DoesNotExist:
                    return Response(
                        {"error": f"Student with roll_no {roll_no} does not exist."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Determine redirect URL based on user designation
            redirect_url = (
                "/examination/submitGradesProf"
                if des in ["Associate Professor", "Professor", "Assistant Professor"]
                else "/examination/submitGrades"
            )

            return Response(
                {
                    "message": "Grades uploaded successfully.",
                    "redirect_url": redirect_url,
                },
                status=status.HTTP_200_OK,
            )

        except Courses.DoesNotExist:
            return Response(
                {"error": "Invalid course ID."}, status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        

"""
API to fetch courses with unverified grades along with unique academic years.

- Only users with the role of 'acadadmin' can access this endpoint.
- Retrieves courses where at least one student's grades are unverified.
- Fetches the academic years associated with unverified grades.

Expected Request:
Headers:
    Authorization: Token <your_auth_token>

Body (JSON):
    {
        "Role": "acadadmin"
    }

Response:
    200 OK - {
        "courses_info": [{"id": 1, "course_name": "Data Structures", ...}],
        "unique_year_ids": [{"year": "2024"}, {"year": "2025"}]
    }
    403 Forbidden - {"success": false, "error": "Access denied."}
"""

class UpdateGradesAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        
        des = request.data.get("Role")
        
        
        if des != "acadadmin":
            return Response(
                {"success": False, "error": "Access denied."},
                status=403,
            )

        # Get unique course IDs for unverified grades
        unique_course_ids = (
            Student_grades.objects.filter(verified=False)
            .values("course_id")
            .distinct()
            .annotate(course_id_int=Cast("course_id", IntegerField()))
        )

        # Retrieve courses
        courses_info = Courses.objects.filter(
            id__in=unique_course_ids.values_list("course_id_int", flat=True)
        )

        # Get unique academic years
        unique_year_ids = Student_grades.objects.values("year").distinct()

        return Response(
            {
                "courses_info": list(courses_info.values()),
                "unique_year_ids": list(unique_year_ids),
            },
            status=200,
        )
    


"""
API to check if grades have been submitted and are verified for a given course and academic year.

- Only users with the role of 'acadadmin' can access this endpoint.
- Verifies if grades exist for the requested course and year.
- Returns student grades if unverified, else indicates if already verified.

Expected Request:
Headers:
    Authorization: Token <your_auth_token>

Body (JSON):
    {
        "Role": "acadadmin",
        "course": "<course_id>",
        "year": "<academic_year>"
    }

Response:
    200 OK - If grades exist but are unverified:
        {
            "registrations": [
                {"id": 1, "roll_no": "CS101001", "grade": "A", ...}
            ]
        }
    200 OK - If already verified:
        {"message": "This course is already verified."}
    400 Bad Request - If required fields are missing:
        {"error": "Both 'course' and 'year' are required."}
    404 Not Found - If no grades exist:
        {"message": "This course is not submitted by the instructor."}
    403 Forbidden - If access is denied:
        {"success": false, "error": "Access denied."}
"""

class UpdateEnterGradesAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        des = request.data.get("Role")

        
        if des != "acadadmin":
            return Response(
                {"success": False, "error": "Access denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get course_id and year from request body
        course_id = request.data.get("course")
        year = request.data.get("year")

        # Validate course_id and year
        if not course_id or not year:
            return Response(
                {"error": "Both 'course' and 'year' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if the course exists with grades for the given year
        course_present = Student_grades.objects.filter(course_id=course_id, year=year)

        if not course_present.exists():
            return Response(
                {"message": "This course is not submitted by the instructor."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if the course is already verified
        verification = course_present.first().verified
        if verification:
            return Response(
                {"message": "This course is already verified."},
                status=status.HTTP_200_OK,
            )

        
        registrations = course_present.values()

        return Response(
            {"registrations": list(registrations)},
            status=status.HTTP_200_OK,
        )
    


"""
API for moderating student grades (updating, verifying, or creating hidden grades).

- Only users with the roles 'acadadmin' or 'Dean Academic' can access this endpoint.
- Updates grades for students based on course and semester.
- Marks grades as verified and supports resubmission if enabled.
- If a student grade doesn't exist, it creates a hidden grade record.
- Returns the updated grades in a downloadable CSV file.

Expected Request:
Headers:
    Authorization: Token <your_auth_token>

Body (JSON):
    {
        "Role": "acadadmin",
        "student_ids": ["20231001", "20231002"],
        "semester_ids": ["5", "5"],
        "course_ids": ["CS101", "CS101"],
        "grades": ["A", "B"],
        "allow_resubmission": "YES"
    }

Response:
    200 OK - CSV file with updated grades
    403 Forbidden - If access is denied:
        {"success": false, "error": "Access denied."}
    400 Bad Request - If required fields are missing or mismatched:
        {"error": "Invalid or incomplete grade data provided."}
    500 Internal Server Error - If any unexpected error occurs:
        {"error": "An error occurred: <error_message>"}
"""

class ModerateStudentGradesAPI(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        
        des = request.data.get("Role")
        if des not in ["acadadmin", "Dean Academic"]:
            return Response(
                {"success": False, "error": "Access denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Extract data from the request
        student_ids = request.data.get("student_ids", [])
        semester_ids = request.data.get("semester_ids", [])
        course_ids = request.data.get("course_ids", [])
        grades = request.data.get("grades", [])
        allow_resubmission = request.data.get("allow_resubmission", "NO")

       
        if (
            not student_ids
            or not semester_ids
            or not course_ids
            or not grades
            or len(student_ids) != len(semester_ids)
            or len(semester_ids) != len(course_ids)
            or len(course_ids) != len(grades)
        ):
            return Response(
                {"error": "Invalid or incomplete grade data provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update or create grades
        for student_id, semester_id, course_id, grade in zip(
            student_ids, semester_ids, course_ids, grades
        ):
            try:
                grade_of_student = Student_grades.objects.get(
                    course_id=course_id, roll_no=student_id, semester=semester_id
                )
                grade_of_student.grade = grade
                grade_of_student.verified = True
                if allow_resubmission.upper() == "YES":
                    grade_of_student.reSubmit = True
                grade_of_student.save()
            except Student_grades.DoesNotExist:
                # Create a new hidden grade if the student grade doesn't exist
                hidden_grades.objects.create(
                    course_id=course_id,
                    student_id=student_id,
                    semester_id=semester_id,
                    grade=grade,
                )

        # Generate CSV file as the response
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="grades.csv"'

        writer = csv.writer(response)
        writer.writerow(["Student ID", "Semester ID", "Course ID", "Grade"])
        for student_id, semester_id, course_id, grade in zip(
            student_ids, semester_ids, course_ids, grades
        ):
            writer.writerow([student_id, semester_id, course_id, grade])

        # Return the CSV response
        return response
    


"""
API to generate a student's academic transcript for a specific semester.

- Only users with the role 'acadadmin' can access this endpoint.
- Fetches the courses and grades of the student for the requested semester.
- Also retrieves all courses registered by the student up to that semester.
- If a grade is unavailable for a course, it returns "Grading not done yet".

Expected Request:
Headers:
    Authorization: Token <your_auth_token>

Body (JSON):
    {
        "Role": "acadadmin",
        "student": "20231001",
        "semester": 3
    }

Response:
    200 OK - Transcript data
    403 Forbidden - If access is denied:
        {"error": "Access denied."}
    400 Bad Request - If required fields are missing:
        {"error": "Student ID and Semester are required."}
    500 Internal Server Error - If any unexpected error occurs:
        {"error": "An error occurred: <error_message>"}
"""

class GenerateTranscript(APIView):
    permission_classes = [IsAuthenticated] 

    def post(self, request):
       
        des = request.data.get("Role")
        student_id = request.data.get("student")
        semester = request.data.get("semester")
        if des != "acadadmin":
            return Response({"error": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

       

        if not student_id or not semester:
            return Response({"error": "Student ID and Semester are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch courses registered for the given student and semester
        courses_registered = Student_grades.objects.filter(
            roll_no=student_id, semester=semester
        )

        
        course_grades = {}

        # Fetch all courses registered up to the given semester
        total_course_registered = Student_grades.objects.filter(
            roll_no=student_id, semester__lte=semester
        )

        for course in courses_registered:
            try:
                # Fetch the grade for the course
                grade = Student_grades.objects.get(
                    roll_no=student_id, course_id=course.course_id
                )

                course_instance = get_object_or_404(Courses, id=course.course_id_id)

                course_grades[course_instance.id] = {
                    "course_name": course_instance.name,
                    "course_code": course_instance.code,
                    "grade": grade.grade,
                }
            except Student_grades.DoesNotExist:
                course_grades[course.course_id.id] = {"message": "Grading not done yet"}

        total_courses_registered_serialized = [
            {
                "course_id": course.course_id.id,
                "semester": course.semester,
                "grade": course.grade,
            }
            for course in total_course_registered
        ]
        response_data = {
            "courses_grades": course_grades,
            "total_courses_registered": total_courses_registered_serialized,
        }

        return Response(response_data, status=status.HTTP_200_OK)
    


"""
API to fetch available academic details and retrieve students for generating transcripts.

- Only users with the role 'acadadmin' can access this endpoint.
- GET: Retrieves the list of available programmes, batches, and specializations.
- POST: Fetches students based on programme, batch, specialization (optional), and semester.

Expected Requests:
1. GET /api/generate-transcript-form/
   Headers:
       Authorization: Token <your_auth_token>
       X-User-Role: acadadmin
   Response:
       200 OK - List of programmes, batches, and specializations
       403 Forbidden - If access is denied:
           {"error": "Access denied. Invalid or missing role."}

2. POST /api/generate-transcript-form/
   Headers:
       Authorization: Token <your_auth_token>
       X-User-Role: acadadmin
   Body (JSON):
       {
           "programme": "B.Tech",
           "batch": "2021",
           "specialization": "AI & ML",
           "semester": 5
       }
   Response:
       200 OK - List of students in the given filters
       403 Forbidden - If access is denied:
           {"error": "Access denied. Invalid or missing role."}
       400 Bad Request - If required fields are missing:
           {"error": "Programme, batch, and semester are required fields."}
"""

class GenerateTranscriptForm(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.headers.get('X-User-Role')
        if not role or role != "acadadmin":
            return Response({"error": "Access denied. Invalid or missing role."}, status=status.HTTP_403_FORBIDDEN)

        programmes = Student.objects.values_list('programme', flat=True).distinct()
        specializations = Student.objects.exclude(
            specialization__isnull=True
        ).values_list('specialization', flat=True).distinct()
        batches = Student.objects.values_list('batch', flat=True).distinct()

        return Response({
            "programmes": list(programmes),
            "batches": list(batches),
            "specializations": list(specializations),
        }, status=status.HTTP_200_OK)

    def post(self, request):
        
        role = request.headers.get('X-User-Role')
        if not role or role != "acadadmin":
            return Response({"error": "Access denied. Invalid or missing role."}, status=status.HTTP_403_FORBIDDEN)

        programme = request.data.get('programme')
        batch = request.data.get('batch')
        specialization = request.data.get('specialization')
        semester = request.data.get('semester')

        if not programme or not batch or not semester:
            return Response(
                {"error": "Programme, batch, and semester are required fields."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if specialization:
            students = Student.objects.filter(
                programme=programme, batch=batch, specialization=specialization
            )
        else:
            students = Student.objects.filter(
                programme=programme, batch=batch
            )

        return Response({
            "students": list(students.values()),
            "semester": semester
        }, status=status.HTTP_200_OK)