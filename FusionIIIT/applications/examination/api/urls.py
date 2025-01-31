
from django.conf.urls import url
from django.urls import path, include
from . import views


urlpatterns = [

    url(r'^exam_view/', views.exam_view, name='exam_view'),
    url(r'^download_template/', views.download_template, name='download_template'),
    url(r'^submitGrades/', views.SubmitGradesView.as_view(), name='submitGrades'),
    url(r'^upload_grades/', views.UploadGradesAPI.as_view(), name='upload_grades'),
    url(r'^update_grades/', views.UpdateGradesAPI.as_view(), name='update_grades'),
    url(r'^update_enter_grades/', views.UpdateEnterGradesAPI.as_view(), name='update_enter_grades'),
    url(r'^moderate_student_grades/', views.ModerateStudentGradesAPI.as_view(), name='moderate_student_grades'),
    url(r'^generate_transcript/', views.GenerateTranscript.as_view(), name='generate_transcript'),
    url(r'^generate_transcript_form/', views.GenerateTranscriptForm.as_view(), name='generate_transcript_form'),

]