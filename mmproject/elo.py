import openskill

from openskill.models import PlackettLuce

model = PlackettLuce()

p1 = model.create_rating([23.035705378196937, 8.177962604389991], "jill678")
print(p1)