#!/usr/bin/python

try:
  from xml.etree import ElementTree
except ImportError:
  from elementtree import ElementTree
import gdata.calendar.data
import gdata.calendar.client
import gdata.acl.data
import atom.data
import time
import useful
import datetime
from dateutil import parser
from time import gmtime, strftime

# Keeping track of data
import pickle
import os.path
import glob
import re

# Email Connection
import imaplib
import email
import re

# Work with other scripts
from timex import parse
from timex import stripPunctuation
from vector import vector

# Debugging
import ipdb as pdb

actuallySchedule = False

# Global variables for vector calculations
wordWeights = {}

# Global variables for data logging
training_results = []
testing_results = []

seen_emails = []
time_vectors = {}
output_log  = []
stopwords = {}


train_count, test_count = [50, 25]

# Credentials to log into Gmail/GCal API
client = gdata.calendar.client.CalendarClient(source='Where\'s A-wheres-a-v1')  # Dummy Google API Key
mail = imaplib.IMAP4_SSL('imap.gmail.com')

# Read in the credentials from an input file
f = open("credentials.txt")
creds = f.readlines()
try:
    assert(len(creds) == 2)
    username = creds[0].strip()
    password = creds[1].strip()
except:
    print """
        Error parsing credentials.txt.

        credentials.txt should contain the username and password
        each on its own line and nothing else.
    """
    sys.exit()


# Authenticate for the calendar and email to be able to access the user's
# email and access the calendarb
def create_connection():
    # Connect to the calendar
    client.ClientLogin(username, password, client.source)
    mail.login(username+'@gmail.com', password)
    mail.list()
    mail.select("INBOX")

    print 'Successfully connected to email and calendar, calendar updating is currently set to %s'%(actuallySchedule)

def load_variables():
    global seen_emails, time_vectors, output_log, stopwords, wordWeights

    # Loads data if it already exists, creates pickle file otherwise
    def load(fileName, data):
        # If the file doesn't exists, make a new file for it
        if not os.path.isfile(fileName):
            with open(fileName, 'wb') as f:
                pickle.dump(data, f)

        # Return the data from the file
        with open(fileName,'rb') as f:
                return pickle.load(f)

    time_vectors = load("time_vectors.p", time_vectors)
    seen_emails  = load("seen_emails.p", seen_emails)
    output_log   = load("output_log.p", output_log)
    stopwords    = load("stopwords.p",stopwords) #this file needs to be given to user, it will not be created
    wordWeights  = load("wordWeights.p",wordWeights)

def log_updates():
    global seen_emails, time_vectors, output_log, wordWeights

    def save(file_name, data):
        with open(file_name, 'wb') as f:
            pickle.dump(data, f)

    save("time_vectors.p", time_vectors)
    save("seen_emails.p", seen_emails)
    save("output_log.p", output_log)
    save("wordWeights.p",wordWeights)

    save("training_results.p", training_results)
    save("testing_results.p", testing_results)

def time_object(year, month, day, hour, minute, second):
    month  = "%02d" % int(month)
    day    = "%02d" % int(day)
    hour   = "%02d" % int(hour)
    minute = "%02d" % int(minute)
    second = "%02d" % int(second)

    return '%s-%s-%sT%s:%s:%s-05:00' % (year, month, day, hour, minute, second)

def parse_email(email_body):

    def get_possible_days(email_body):
        possible_days = []

        parsed_results = parse(email_body)

        assert(len(parsed_results[0]) == len(parsed_results[1]))
        for i in range(len(parsed_results[0])):
                possible_days.append( ('2014',
                                     parsed_results[1][i],
                                     parsed_results[0][i]) )

        return possible_days


    def get_possible_times_filtered(possible_days_p):
        possible_times = []         # Stores tuples (start_time, end_time)
        duration = 60               # Currently duration of event is an hour

        # Generate all the possible times for all the possible days
        for possible_day in possible_days_p:
            day_start_str = time_object(possible_day[0], possible_day[1],
                                        possible_day[2], 0, 0, 0)
            day_end_str   = time_object(possible_day[0], possible_day[1],
                                        possible_day[2], 23, 59, 59)

            day_start_time = parser.parse(day_start_str)
            day_end_time   = parser.parse(day_end_str)

            while(day_start_time < day_end_time):
                new_possible_time = (day_start_time, day_start_time + datetime.timedelta(minutes=duration), None)
                possible_times.append(new_possible_time)
                day_start_time += datetime.timedelta(minutes=30)

            # Faster to filter out conflicts on per day basis than at the end
            for e_conflict in findConflicts(day_start_str, day_end_str):
                conflict_start = parser.parse(e_conflict.when[0].start)
                conflict_end   = parser.parse(e_conflict.when[0].end)

                # Before old times were filtered out
                # Filter out the bad times for that event
                possible_times = filter(lambda time: (time[1] <= conflict_start or conflict_end <= time[0]), possible_times)

                # List comprehension
                # Third possible time element is the name of the conflict. That is added to the list.
                # possible_times = [(time[0], time[1], time[2]) if (time[1] <= conflict_start or conflict_end <= time[0]) else (time[0], time[1], e_conflict) for time in possible_times]
        return possible_times

    def findConflicts(start_date, end_date):
        # Construct the calendar query
        query = gdata.calendar.client.CalendarEventQuery()
        query.start_min = start_date
        query.start_max = end_date

        feed = client.GetCalendarEventFeed(q=query) # Execute the query

        return feed.entry



    # Acutal function logic
    days = get_possible_days(email_body)
    possible_free_times = get_possible_times_filtered(days)
    return possible_free_times

def rank_times(times,email):
    global wordWeights
    global stopwords
    global time_vectors
    emailVector = None

    #loads vector, creates one if necessary
    def loadVector(time):
        global time_vectors
        time = str(time[0].hour)+"-"+str(time[1].minute) #string representation of time object
        #check if the vector exists first
        if time in time_vectors:
            return time_vectors[time]
        #if not, return nothine
        else:
            return None

    def calculateWordWeights(email,wordWeights,emailVector):
        importantWordsFromEmail = {}
        sum = 0

        #count the number of words that are not stopwords and how often they occur
        for word in email.split():
            #TODO: Use regex to remove all punctuation here
            if word not in stopwords:
                importantWordsFromEmail[word] = importantWordsFromEmail.get(word,0)+1
                sum+=1

        #update the global count of each words
        for word in importantWordsFromEmail.keys():
            wordWeights[word] = wordWeights.get(word,0)+importantWordsFromEmail[word]

        #update the total number of words
        wordWeights["totalNumbers"] = wordWeights.get("totalNumbers",0) + sum

        #create a vector representing the email
        emailVector = vector(importantWordsFromEmail,wordWeights)
        return emailVector


    def similarity_test(times,emailVector):
        rankResults = {}
        for time in times:
            timeVector = loadVector(time)
            #check if this time already has a vector

            if timeVector != None:
                #if it does, perform similarity calculations
                simScore = timeVector.similarityTest(emailVector,wordWeights)
                rankResults[time] = simScore
        return rankResults

    def sortResults(rankedInOrder,times):
        #sort the results so that the top similarity scores are first then the unranked times
        rankedInOrder = sorted(rankResults,key=rankResults.get)
        unranked = []
        for time in times:
            if time not in rankedInOrder: #is this one of the top results? if not, add it to unranked list
                unranked.append(time)
        # for t in rankedInOrder:
            # print "Time: %s, Score: %s"%(t,rankResults[t])
        rankedInOrder.extend(unranked) #combine ranked and unranked into one list
        return rankedInOrder

    def prompt_user(times):

        def isNumber(str):
            try:
                int(str)
                return True
            except:
                return False

        limit = 50
        # Print out the possible times, with an associated index
        print 'Please select a start time for your event: '

        for i, possible_time in enumerate(times):
            if possible_time[2]:
                print '%02d :: %s - %s \t*Conflict: %s from %s to %s' % (i,
                                                                         possible_time[0].strftime("%a %m-%d %I:%M%p"),
                                                                         possible_time[1].strftime("%I:%M%p"),
                                                                         possible_time[2].title.text,
                                                                         parser.parse(possible_time[2].when[0].start).strftime("%I:%M%p"),
                                                                         parser.parse(possible_time[2].when[0].end).strftime("%I:%M%p"))
            else:
                print '%02d :: %s - %s' % (i, possible_time[0].strftime("%a %m-%d %I:%M%p"), possible_time[1].strftime("%I:%M%p"))
        print

        # Continue to prompt for value while it is not valid
        user_selection = ""
        while not isNumber(user_selection) or int(user_selection) < -1 or int(user_selection) >= len(times):
            user_selection = raw_input("Select Most Optimal Time (Enter -1 to not schedule any event): ")

        try:
            user_selection = int(user_selection)
            if (user_selection == -1):
                return user_selection
        except:
            print("Invalid input. Please enter a valid time")
        print "\n"

        return user_selection

    def updateVector(user_choice,sortedResults,emailVector,time_vectors):
        time = sortedResults[user_choice]
        timeVector = loadVector(time)
        if timeVector == None:
            timeVector = emailVector
        else:
            timeVector.appendVector(emailVector)
        time_str = str(time[0].hour)+"-"+str(time[1].minute)
        time_vectors[time_str] = timeVector

    def log_changes():
        global seen_emails, time_vectors, wordWeights

        def save(file_name, data):
            with open(file_name, 'wb') as f:
                pickle.dump(data, f)

        save("time_vectors.p", time_vectors)
        save("seen_emails.p", seen_emails)
        save("wordWeights.p",wordWeights)

    emailVector = calculateWordWeights(email,wordWeights,emailVector) #update the global count of all words/their weights
    rankResults = similarity_test(times,emailVector) #perform similarity tests for all vectors (time slots) which we have data for
    sortedResults = sortResults(rankResults ,times) #sort the results according to the similarity results
    user_choice = prompt_user(sortedResults) #ask the user which time they would actually like to schedule
    if user_choice != -1:
        updateVector(user_choice,sortedResults,emailVector,time_vectors) # associate this email vector with the time the user has chosen

        return sortedResults, user_choice
    else:
        log_changes() #save updates
        return False, False

def check_for_new_emails_and_prompt():
    status, data = mail.search(None, 'ALL')     # Grab all the emails
    email_ids = data[0].split()                 # and their email ids

    # THE OLD WAY OF GOING THROUGH THE EMAILS:
    # Scan the list from new to old.
    # for i in range(len(email_ids) -1, -1, -1):
    #     email_id = email_ids[i]             # Fetch that email
    #     result, data = mail.fetch(email_id, "(RFC822)")

    #     raw_email = data[0][1]              # Turn it into an email object
    #     email_obj = email.message_from_string(raw_email)

    #     #TODO: fix bug where body is a list of message objects
    #     # Payload can either be a list (HTML & Reg Version), or just Reg
    #     while isinstance(email_obj._payload, list):
    #         email_obj = email_obj._payload[0]

    #     body = email_obj._payload

    #     subj   = email_obj["Subject"]
    #     sender = email_obj["From"]

    #     # Seen this email before? -> Seen all older. Terminate
    #     if ( hash(str(subj)), hash(str(body)) ) in seen_emails:
    #         return

    #     # If you haven't seen this before handle accordingly
    #     process_email(subj, body, sender)

    print "Beginning Training: \n"

    # Grab all of files
    files = glob.glob("enron/*.txt")
    minimumStart = min(len(files),train_count)

    for i in range(0, minimumStart):
        train_file(files[i])

    print "Beginning Testing: \n"
    for i in range(minimumStart, minimumStart+test_count):
        test_file(files[i])


def train_file(file_name):
    print_separation()
    print_separation()
    print
    print "Training on File: %s" % file_name
    f = open(file_name, "r")
    body = strip_enron_body(f.readlines())

    possible_times = parse_email(stripPunctuation(body))
    if len(possible_times) > 0:
        print "%s" % body
        possible_times, user_selection = rank_times(possible_times, body)
        if (user_selection == -1):
            print("\nNo event scheduled for email.")
            return


        training_results.append( (user_selection, possible_times, body) )

def test_file(file_name):
    print_separation()
    print_separation()
    print

    print "Testing on File: %s" % file_name
    f = open(file_name, "r")
    body = strip_enron_body(f.readlines())


    possible_times = parse_email(stripPunctuation(body))
    if len(possible_times) > 0:
        print "%s" % body
        possible_times, user_selection = rank_times(possible_times, body)
        if (user_selection == -1):
            print("\nNo event scheduled for email.")
            return


        testing_results.append( (user_selection, possible_times, body) )

def process_email(subject, body, sender):
    global output_log

    seen_emails.append( (hash(str(subject)), hash(str(body))) )
    #check if this email requires a new appointment
    body = get_most_recent_email_body(body)
    body = stripPunctuation(body)
    possible_times = parse_email(body)

    if len(possible_times) > 0:
        print "\nProcessing Email:"
        print "\nSubject: %s" % subject
        print "From: %s" % sender
        print "%s" % body
        possible_times, user_selection = rank_times(possible_times,body)

        # Catch the case where user_selection is -1
        if (user_selection == -1):
            print("\nNo event scheduled for email.")
            return

        # store_user_choice(user_selection)
        if possible_times and user_selection:
            if actuallySchedule:
                schedule_calendar_event(possible_times[user_selection])

            # TODO: Append that body to the appropriate time vector
            prettyPossible_times = []
            for time in possible_times:
                temp = str(time[0])
                prettyPossible_times.append(temp)
            output_log.append( (prettyPossible_times, user_selection) )

def schedule_calendar_event(time, title=None):
    event_title = ""
    if (title == None):
        while not event_title:
            event_title = raw_input("What would you like to call your event: ")
    else:
        event_title = title

    useful.InsertSingleEvent(client,
                             event_title,
                             None,
                             None,
                             time[0].strftime("%Y-%m-%dT%H:%M:%S") + "-05:00",
                             time[1].strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"
                             )

def get_most_recent_email_body(e_body):
    email_pattern = e_pat = re.compile('([\w\-\.]+@(\w[\w\-]+\.)+[\w\-]+)')
    return re.split(email_pattern, e_body)[0]

def initialize_seen_email():
    global seen_emails

    def save(file_name, data):
            with open(file_name, 'wb') as f:
                pickle.dump(data, f)

    seen_emails = []
    status, data = mail.search(None, 'ALL')     # Grab all the emails
    email_ids = data[0].split()                 # and their email ids

    # Scan the list from new to old.
    max_emails = 5
    iteration = 0
    for i in range(len(email_ids) -1, -1, -1):
        if iteration > max_emails:
            break

        email_id = email_ids[i]             # Fetch that email
        result, data = mail.fetch(email_id, "(RFC822)")


        raw_email = data[0][1]              # Turn it into an email object
        email_obj = email.message_from_string(raw_email)

        #TODO: fix bug where body is a list of message objects
        # Payload can either be a list (HTML & Reg Version), or just Reg
        while isinstance(email_obj._payload, list):
            email_obj = email_obj._payload[0]

        body = email_obj._payload

        subj   = email_obj["Subject"]
        sender = email_obj["From"]

        # Seen this email before? -> Seen all older. Terminate
        seen_emails.append( (hash(str(subj)), hash(str(body))) )

        iteration += 1

    save("seen_emails.p", seen_emails)

def strip_enron_body(body):
    line_begins = ['Date:', 'Message-ID', 'Mime-Version:',
        'Content-Type:', 'X-From:', 'X-To', 'X-cc', 'X-bcc', 'X-Folder',
        'X-Origin:', 'X-FileName', 'Content-Transfer-Encoding:', 'Sent:']
    result = body
    for to_filter in line_begins:
        result = filter(lambda n: not n.startswith(to_filter), result)
    return "".join(result)

def print_separation():
    print "#################################################################"
def main():
    create_connection()
    load_variables()
    check_for_new_emails_and_prompt()
    log_updates()

if __name__ == '__main__':
    main()
