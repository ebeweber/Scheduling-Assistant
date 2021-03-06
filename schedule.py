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
import datetime
from dateutil import parser

from time import gmtime, strftime

# Keeping track of data
import pickle

# Email Connection
import imaplib
import email

# Work with other scripts
import timex

# Debugging
import pdb
import sys

# Global variables for authentication
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
    mail.select("INBOX") # connect to inbox.

    print 'Successfully connected to email and calendar!'

# Retrieves the move recent email
def check_email():
    email_text = get_most_recent_email()
    print "Email text: \n" + email_text
    return email_text

#NLP to detect events from email
def parse_email(email_body):
    # the desired time format is: %Y-%m-%DT%H:%M:%S

    #t is an array of relative time objects, time objects, day_objects, month objects, and year objects detected in text
    t,email_text = timex.parse(email_body)

    def findYear(t):
        print "Year: " + str(t[0])

    def findMonth(t):
        print "Month: "+ str(t[1])

    def findDay(t):
        print "Day: "+ str(t[2])

    def findHour(t):
        print "Hour: " +str(t[3])

    def findMinute(t):
        print "Minute: "+ str(t[4])

    def findSecond(t):
        print "Second: " + str(t[5])

    print "Parsed entities: Y:%s M:%s D:%s H:%s M:%s S:%s" % (t[0], t[1], t[2], t[3], t[4], t[5])
    return t, email_text

# Checks for calendar conflicts between the start date and the end date
# Returns a list of those conflicts
def findConflicts(start_date, end_date):
    # Construct the calendar query
    query = gdata.calendar.client.CalendarEventQuery()
    query.start_min = start_date
    query.start_max = end_date

    print
    print 'Grabbing events between %s -- %s' % (start_date, end_date)
    feed = client.GetCalendarEventFeed(q=query) # Execute the query
    for i, an_event in enumerate(feed.entry):   # Go over the calendar and pring out the events
        print '\t%s. %s' % (i, an_event.title.text)
    print

    return feed.entry


# Found here: https://developers.google.com/google-apps/calendar/v2/developers_guide_python#CreatingSingle
def InsertSingleEvent(calendar_client=client,
                                title=None,
                                content=None,
                                where=None,
                                start_time=None,
                                end_time=  None):
    event = gdata.calendar.data.CalendarEventEntry()
    event.title = atom.data.Title(text=title)
    event.content = atom.data.Content(text=content)
    event.where.append(gdata.calendar.data.CalendarWhere(value=where))
    if start_time is None:
      # Use current time for the start_time and have the event last 1 hour
      start_time = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
      end_time = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(time.time() + 3600))
    event.when.append(gdata.calendar.data.When(start=start_time, end=end_time))
    print start_time, end_time
    new_event = calendar_client.InsertEvent(event)
    print 'New single event inserted: %s' % (new_event.id.text,)
    print '\tEvent edit URL: %s' % (new_event.GetEditLink().href,)
    print '\tEvent HTML URL: %s' % (new_event.GetHtmlLink().href,)
    return new_event

# Takes the entities and constructs them appropriately in the format
# google's API accepts and likes.
# TODO: Currently the timezone is hardcoded in, should eventually be fixed
def time_object(year, month, day, hour, minute, second):
    month  = "%02d" % int(month)
    day    = "%02d" % int(day)
    hour   = "%02d" % int(hour)
    minute = "%02d" % int(minute)
    second = "%02d" % int(second)

    return '%s-%s-%sT%s:%s:%s-06:00' % (year, month, day, hour, minute, second)

# Prompts user for a time by checking the parsed information
# and asking what time works best, currently only selects the best hour
def prompt_user_for_time(parsed, duration, email_body):
    # Load saved information from past decision
    past_decisions = pickle.load(open("save.p", "rb"))

    # Construct string for day start/end for Google's Cal API
    day_start_str = time_object(parsed[0][0], parsed[1][0], parsed[2][0], 0, 0, 0)
    day_end_str   = time_object(parsed[0][0], parsed[1][0], parsed[2][0], 23, 59, 59)

    # Construct the time obejct for simple comparisons
    day_start_time = parser.parse(day_start_str)
    day_end_time = parser.parse(day_end_str)

    possible_times = []             # Generate a list of all the possible times that day
    while (day_start_time < day_end_time):
        possible_time = (day_start_time, day_start_time + datetime.timedelta(minutes=duration))
        possible_times.append(possible_time)
        day_start_time = day_start_time + datetime.timedelta(minutes=30)    # Times currently generated on the half hour

    # Filter out the times that are not valid
    for e_conflict in findConflicts(day_start_str, day_end_str):
        conflict_start = parser.parse(e_conflict.when[0].start)
        conflict_end   = parser.parse(e_conflict.when[0].end)

        # Filter out the bad times for that event
        possible_times = filter(lambda time: (time[1] <= conflict_start or conflict_end <= time[0]), possible_times)

    # Print out the possible times, with an associated index
    print 'Please select a start time for your event: '
    for i, possible_time in enumerate(possible_times):
        print '%02d :: %s - %s' % (i, possible_time[0].strftime("%a %m-%d %I:%M%p"), possible_time[1].strftime("%I:%M%p"))


    print               # Prompt user for a selection
    user_selection = int(input("Please select the most optimal time: "))
    print 'The user selected the following time: %s' % possible_times[user_selection][0]

    # Save the new decision. Saved in (choices, decision, email_body) triples.
    new_decision = (possible_times, possible_times[user_selection], email_body)
    past_decisions.append(new_decision)

    pickle.dump(past_decisions, open("save.p", "wb"))   # Save the past decisions
                                                        # with the new one

    return possible_times[user_selection]

# Schedule event based on the parsed infromation and the email body
def schedule_event(email_body, parsed):
    event_name = raw_input('Name of the event: ')                           # The event needs some name
    event_duration = int(raw_input('Duration of the event (minutes): '))    # and a duration

    print "Scheduling an event now.."
    if len(parsed[3]) != 1:     # Unclear hour, this assumes definite date TODO: was == 1 while regex would always return something
        possible_time = prompt_user_for_time(parsed, event_duration, email_body)    # Grab the time the user wants

        # Schedule at the time requested by the users
        InsertSingleEvent(client,
                          event_name,
                          None,
                          None,
                          possible_time[0].strftime("%Y-%m-%dT%H:%M:%S") + "-06:00", # This is hacky. %:z gives me what I want
                          possible_time[1].strftime("%Y-%m-%dT%H:%M:%S") + "-06:00"  # but I was unable to get it to work
                          )
    else:           # Otherwise schedule, defaults to a duration of 1 hour
        start_time = time_object(parsed[0][0], parsed[1][0], parsed[2][0], parsed[3][0], parsed[4][0], parsed[5][0])
        # TODO: Have end time incorporate the duration
        end_time = time_object(parsed[0][0], parsed[1][0], parsed[2][0], str(int(parsed[3][0]) + 1), parsed[4][0], parsed[5][0])
        InsertSingleEvent(client, event_name, None, None, start_time, end_time)

# Returns the body of the user's most recent email
def get_most_recent_email():
    status, data = mail.search(None, 'ALL')
    ids = data[0] # data is a list.
    id_list = ids.split() # ids is a space separated string
    latest_email_id = id_list[-1] # get the latest
    result, data = mail.fetch(latest_email_id, "(RFC822)") # fetch the email body (RFC822) for the given ID


    raw_email = data[0][1] #this variable is an "email" object
    em = email.message_from_string(raw_email)

    if isinstance(em._payload, list):
        body = em._payload[0]._payload
    else:
        body = em._payload

    return body

def main():
    create_connection()                 # need to connect to calendar now
    email_body = check_email()
    parsed, email_text  = parse_email(email_body)

    # Prompt the user to schedule an event
    should_schedule = raw_input("Would you like to schedule an event? ")

    if (should_schedule[0] == 'y' or should_schedule[0] == 'Y'):
        schedule_event(email_text, parsed)

if __name__ == "__main__":
    main()
