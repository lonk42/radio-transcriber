import speech_recognition
from tempfile import TemporaryFile
from pydub import AudioSegment
from os import walk,path
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import time
import pymongo
from datetime import datetime

class Recording_Processor:

	def __init__(self):

		# Initialize
		self.recognizer = speech_recognition.Recognizer()

		# Connect to mongo
		mongo_client = pymongo.MongoClient("mongodb://mongo:27017", username="transcriber", password="transcriber")
		mongo_db = mongo_client["transcriber"]
		self.mongo_collection = mongo_db["transcriptions"]

		# Create watchdog file listener
		watchdog_handler = PatternMatchingEventHandler(patterns=["*"], ignore_patterns=None, ignore_directories=True, case_sensitive=False)
		watchdog_handler.on_created = self.on_created
		# TODO create a delete handler
		file_observer = Observer()
		file_observer.schedule(watchdog_handler, "/recordings", recursive=True)
		file_observer.start()

		# List files in the recordings directory
		for root, dirs, files in walk("/recordings"):

			# Skip if there are no files here
			if len(files) == 0:
				continue

			# Call the transcriber against the file
			for file in files:
				self.transcribe(root=root, file=file)

		# Live forever
		while True:
			time.sleep(10)

	def on_created(self, event):
		self.transcribe(file_path = event.src_path)

	def transcribe(self, root=None, file=None, file_path=None):

		# TODO can do the argument handling better here
		if file_path is not None:
			root = path.dirname(file_path)
			file = path.basename(file_path)
		else:
			file_path = path.join(root,file)

		# Only MP3 is supported
		if not file.endswith(".mp3"):
			print("Ignoring file '%s' as its not an mp3...'" % (file))
			return

		# If we have this file already, get the id. Otherwise insert it
		cursor = self.mongo_collection.find_one({"filename": file})
		if cursor is not None:
			file_id = cursor['_id']
			cursor = self.mongo_collection.find_one({"_id": file_id})

			# Exit if there is a transcription of this type already
			if cursor['transcriptions'].get('sphinx') is not None:
				return

		else:
			file_id = self.mongo_collection.insert_one({"filename": file, "transcriptions": {}}).inserted_id

		print("Begining transcription on file '%s'" % (file_path))

		# Convert file to a wav
		with TemporaryFile() as temp_file:
			sound = AudioSegment.from_mp3(file_path)
			sound.export(temp_file, format="wav")

			# Crack open this sucker
			with speech_recognition.AudioFile(temp_file) as source:
				audio = self.recognizer.record(source)

			# Run file over sphinx and insert to db
			try:
				transcription = self.recognizer.recognize_sphinx(audio)
				print("Sphinx transcription: '%s'" % (transcription))
			except speech_recognition.UnknownValueError:
				print("Sphinx could not understand audio")
			except speech_recognition.RequestError as e:
				print("Sphinx error; {0}".format(e))

			# Update the document with the result
			self.mongo_collection.update_one(
				{"_id": file_id},
				{
					"$set": { 
						"transcriptions.sphinx": {
							"transcription": self.recognizer.recognize_sphinx(audio),
							"date": datetime.now()
						}
					}
				}
			)
		
if __name__ == "__main__":
	Recording_Processor()
