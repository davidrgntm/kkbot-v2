# Reference photo final patch

Added to employee cabinet:
- upload high-quality AI reference photo
- preview current reference photo
- save into face_templates
- update users.avatar_file_id with reference path

Routes:
- POST /cabinet/reference-photo
- GET /face-reference/{telegram_id}

Only the employee themself or admin can view the reference image.
