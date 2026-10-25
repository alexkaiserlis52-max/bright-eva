import openai
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
import os



# LEGACY PROTOTYPE — kept for reference only; the live app is app.py + openai_reports.py.
# API key now comes from the environment (.env), never hardcode it here.
from dotenv import load_dotenv
load_dotenv()
api_key = os.environ.get("OPENAI_API_KEY")

openai.api_key = api_key

# Authenticate with Google Sheets API using your service account credentials
scopes = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
credentials = Credentials.from_service_account_file(
    'insudies-e24d0d9618d5.json',
    scopes=scopes
)

gc = gspread.authorize(credentials)



def ChildrenAssessemnt(StudID,date,AssesType):
    # Open The two sheets. Pre is for PreAssesment from the parent. Fo is from the teacher (can contain multiple assessments)
    PreAssesment = gc.open('PreAssessment').sheet1
    FoAssesment = gc.open('FoAssessment').sheet1
    SelfAssessment = gc.open('SelfAssessment').sheet1

    headerPre = PreAssesment.row_values(1)
    headerFo = FoAssesment.row_values(1)
    headerSelf = SelfAssessment.row_values(1)
    PreAssesment_column_index = headerPre.index("Κωδικός Μαθητή") + 1
    FoAssesment_column_index = headerFo.index("Κωδικός Μαθητή") + 1
    SelfAssesment_column_index = headerSelf.index("Κωδικός Μαθητή") + 1
    PreAssesment_date_index = headerPre.index("Χρονική σήμανση") + 1
    FoAssesment_date_index = headerFo.index("Χρονική σήμανση") + 1
    SelfAssesment_date_index = headerSelf.index("Χρονική σήμανση") + 1
    
    # Search for the matching row
    matching_rows_for_Pre = []
    matching_rows_for_Fo = []
    matching_rows_for_Self = []
        
    for row in PreAssesment.get_all_values()[1:]:
        date_string =  row[PreAssesment_date_index - 1]
        date_string = date_string.replace("π.μ.", "PM").replace("π.μ.", "AM")
        date_obj = datetime.strptime(date_string, "%d/%m/%Y %I:%M:%S %p")
        formatted_date = date_obj.strftime("%Y-%m-%d")
        if row[PreAssesment_column_index - 1] == StudID and formatted_date<date:
            matching_rows_for_Pre.append(row)

    for row in FoAssesment.get_all_values()[1:]:
        date_string =  row[FoAssesment_date_index - 1]
        date_string = date_string.replace("π.μ.", "PM").replace("π.μ.", "AM")
        date_obj = datetime.strptime(date_string, "%d/%m/%Y %I:%M:%S %p")
        formatted_date = date_obj.strftime("%Y-%m-%d")
        if row[FoAssesment_column_index - 1] == StudID and formatted_date<date:
            matching_rows_for_Fo.append(row) 
            
    for row in SelfAssessment.get_all_values()[1:]:
        date_string =  row[SelfAssesment_date_index - 1]
        date_string = date_string.replace("π.μ.", "PM").replace("π.μ.", "AM")
        date_obj = datetime.strptime(date_string, "%d/%m/%Y %I:%M:%S %p")
        formatted_date = date_obj.strftime("%Y-%m-%d")
        if row[SelfAssesment_column_index - 1] == StudID and formatted_date<date:
            matching_rows_for_Self.append(row) 
            
    number_of_Pre_Assessments = len(matching_rows_for_Pre)
    number_of_Fo_Assessments = len(matching_rows_for_Fo)
    number_of_Self_Assessments = len(matching_rows_for_Self)
    
    # Initialize a list to store dictionaries for each row
    FoAssesments_list = []
    PreAssesments_list = []
    SelfAssesments_list = []

    # Iterate through each matching row and create a dictionary for each row
    if number_of_Fo_Assessments>0:
        for row in matching_rows_for_Fo:
            row_data = {}  # Initialize a dictionary for the row
            for i, cell_value in enumerate(row):
                column_name = headerFo[i]
                row_data[column_name] = cell_value  # Add data to the dictionary
            FoAssesments_list.append(row_data)  # Append the dictionary to the list
        key_value_string = ""

    
    if number_of_Pre_Assessments>0:
        for row in matching_rows_for_Pre:
            row_data = {}  # Initialize a dictionary for the row
            for i, cell_value in enumerate(row):
                column_name = headerPre[i]
                row_data[column_name] = cell_value  # Add data to the dictionary
            PreAssesments_list.append(row_data)  # Append the dictionary to the list
            
    if number_of_Self_Assessments>0:
        for row in matching_rows_for_Self:
            row_data = {}  # Initialize a dictionary for the row
            for i, cell_value in enumerate(row):
                column_name = headerPre[i]
                row_data[column_name] = cell_value  # Add data to the dictionary
            SelfAssesments_list.append(row_data)  # Append the dictionary to the list

    key_value_string = ""

    The_foassems_in_String = []
    for row_data in FoAssesments_list:
        # Iterate through key-value pairs in the dictionary
        for key, value in row_data.items():
            if key == "Χρονική σήμανση":
                key_value_string += f"Date the assesment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_foassems_in_String.append(key_value_string)
        key_value_string = ""

    key_value_string = ""

    The_preassems_in_String = []
    for row_data in PreAssesments_list:
        # Iterate through key-value pairs in the dictionary
        for key, value in row_data.items():
            if key == "Χρονική σήμανση":
                key_value_string += f"Date the assesment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_preassems_in_String.append(key_value_string)
        key_value_string = ""
    
    The_Selfassems_in_String = []
    for row_data in SelfAssesments_list:
        # Iterate through key-value pairs in the dictionary
        for key, value in row_data.items():
            if key == "Χρονική σήμανση":
                key_value_string += f"Date the assesment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_Selfassems_in_String.append(key_value_string)
        key_value_string = ""


    preass_reports = []
    formass_reports = []
    selfass_reports = []
    for assessments in The_preassems_in_String:
        prompt = f"questions/fields seperated by ---"
        prompt += f"number ranking from 1 to 5"
        prompt += f"Parent Assessment: {assessments}" 
        content = f"With the role of a Teacher, {AssesType}"
    
        message=[
            {
            "role": "system",
            "content": content
            },
            {
            "role": "user",
            "content": prompt
            }
        ]

        # # Make an API request to generate the report
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # You can choose the appropriate engine
            messages=message,
            max_tokens=120
        )
        # Print the generated report
        response_message = response["choices"][0]["message"]["content"]
        preass_reports.append(response_message)
       # print(preass_reports)
        
    
    #Getting the prompt for the fo Assessments

    count = 1
    while count<=number_of_Fo_Assessments:
        prompt = f"questions/fields seperated by ---"
        prompt += f"number ranking from 1 to 5"
        prompt += f"Teacher Assessments (this is number {count}/in total of {number_of_Fo_Assessments}): {The_foassems_in_String[count-1]}. " 
        content = f"With the role of a Teacher, {AssesType}, stating the progress after each one. Give a final report on the last one"    
        count+=1
        message=[
            {
            "role": "system",
            "content": content
            },
            {
            "role": "user",
            "content": prompt
            }
        ]

        # # Make an API request to generate the report
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # You can choose the appropriate engine
            messages=message,
            max_tokens=120
        )
        # Print the generated report
        response_message = response["choices"][0]["message"]["content"]
        formass_reports.append(response_message)
        #print(formass_reports)


    count = 1
    while count<=number_of_Self_Assessments:
        prompt = f"questions/fields seperated by ---"
        prompt += f"number ranking from 1 to 5"
        prompt += f"Self Assessments (this is number {count}/in total of {number_of_Fo_Assessments}): {The_foassems_in_String[count-1]}. " 
        content = f"With the role of a Teacher, {AssesType}."    
        count+=1
        message=[
            {
            "role": "system",
            "content": content
            },
            {
            "role": "user",
            "content": prompt
            }
        ]

        # # Make an API request to generate the report
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # You can choose the appropriate engine
            messages=message,
            max_tokens=120
        )
        # Print the generated report
        response_message = response["choices"][0]["message"]["content"]
        selfass_reports.append(response_message)
        #print(selfass_reports)


    prompt = f"compine the reports in the lists: {preass_reports} {formass_reports}, {selfass_reports}. " 
    content = f"With the role of a Teacher, {AssesType}. Give a total report with the progress of the kid with important dates, if any."    
    count+=1
    message=[
        {
        "role": "system",
        "content": content
        },
        {
        "role": "user",
        "content": prompt
        }
    ]

    # # Make an API request to generate the report
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # You can choose the appropriate engine
        messages=message,
        max_tokens=120
    )
    # Print the generated report
    response_message = response["choices"][0]["message"]["content"]
    print(response_message)

    
ChildrenAssessemnt("test",str("2023-09-04")," summarize the report with the date of the report, in maximum 120 tokens")