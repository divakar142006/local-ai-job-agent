import datetime
import os
from peewee import *
from contextlib import contextmanager

# Define the database path
DB_DIR = r"D:\job-agent\database"
DB_PATH = os.path.join(DB_DIR, "jobs.db")

# Create the database directory if it doesn't exist
os.makedirs(DB_DIR, exist_ok=True)

# Initialize the SQLite database connection
db = SqliteDatabase(DB_PATH)

class BaseModel(Model):
    """A base model that will use our SQLite database."""
    class Meta:
        database = db

class Job(BaseModel):
    """
    Represents a job listing found by the agent.
    """
    url = TextField(null=True)
    title = TextField()
    company = TextField()
    location = TextField(null=True)
    description = TextField()
    requirements = TextField(null=True)
    salary = TextField(null=True)
    match_score = IntegerField(default=0)
    match_reasoning = TextField(null=True)
    status = TextField(default='new') # choices: new/matched/applied/rejected/saved
    source = TextField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)
    updated_at = DateTimeField(default=datetime.datetime.now)

    @classmethod
    def get_by_status(cls, status: str):
        """Get jobs filtered by status."""
        return cls.select().where(cls.status == status)
    
    @classmethod
    def get_recent(cls, limit: int = 20):
        """Get the most recently created jobs."""
        return cls.select().order_by(cls.created_at.desc()).limit(limit)
    
    def save(self, *args, **kwargs):
        """Override save to update updated_at."""
        self.updated_at = datetime.datetime.now()
        return super().save(*args, **kwargs)

class Application(BaseModel):
    """
    Represents an application made to a job.
    """
    job = ForeignKeyField(Job, backref='applications')
    cover_letter = TextField(null=True)
    custom_answers = TextField(null=True) # Could store JSON string
    resume_used = TextField(null=True)
    status = TextField(default='draft') # choices: draft/ready/submitted/failed
    applied_at = DateTimeField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)

    @classmethod
    def get_pending(cls):
        """Get all applications that are ready to be submitted."""
        return cls.select().where(cls.status == 'ready')

class Notification(BaseModel):
    """
    Represents a notification sent to the user.
    """
    job = ForeignKeyField(Job, null=True, backref='notifications')
    message = TextField()
    notification_type = TextField() # choices: match/apply/question/error
    sent_via = TextField() # choices: sms/dashboard
    sent_at = DateTimeField(default=datetime.datetime.now)

def get_db():
    """Returns the database instance."""
    return db

def initialize_db():
    """
    Creates the database tables if they do not exist.
    Run this function when starting the application.
    """
    with db:
        db.create_tables([Job, Application, Notification])
        print("Database initialized and tables created (if they didn't exist).")

@contextmanager
def db_session():
    """
    Context manager for database sessions.
    Useful for ensuring the connection is closed after use.
    """
    if db.is_closed():
        db.connect()
    try:
        yield db
    finally:
        if not db.is_closed():
            db.close()
