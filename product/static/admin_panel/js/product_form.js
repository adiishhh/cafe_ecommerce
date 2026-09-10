document.addEventListener('DOMContentLoaded', function () {

    let cropper = null;
    let currentInput = null;

    const modal = document.getElementById('crop-modal');
    const cropImage = document.getElementById('crop-image');
    const cropButton = document.getElementById('crop-button');
    const cancelButton = document.getElementById('crop-cancel');

    const imageInputs = document.querySelectorAll(
        '.image-upload input[type="file"]'
    );


    imageInputs.forEach(function (input) {

        input.addEventListener('change', function () {

            const file = input.files[0];

            if (!file) {
                return;
            }

            if (!file.type.startsWith('image/')) {
                input.value = '';

                alert('Please select an image file.');

                return;
            }

            currentInput = input;

            const reader = new FileReader();

            reader.onload = function (event) {

                cropImage.src = event.target.result;

                modal.classList.add('show');

                if (cropper) {
                    cropper.destroy();
                }

                cropImage.onload = function () {

                    cropper = new Cropper(
                        cropImage,
                        {
                            aspectRatio: 1,
                            viewMode: 1,
                            autoCropArea: 0.9,
                            responsive: true,
                            background: false,
                        }
                    );

                };

            };

            reader.readAsDataURL(file);

        });

    });


    cropButton.addEventListener('click', function () {

        if (!cropper || !currentInput) {
            return;
        }

        const canvas = cropper.getCroppedCanvas({
            width: 800,
            height: 800,
            imageSmoothingEnabled: true,
            imageSmoothingQuality: 'high',
        });


        canvas.toBlob(
            function (blob) {

                const originalFile = currentInput.files[0];

                const fileName =
                    originalFile.name
                        .replace(/\.[^/.]+$/, '') +
                    '.jpg';


                const processedFile = new File(
                    [blob],
                    fileName,
                    {
                        type: 'image/jpeg',
                        lastModified: Date.now(),
                    }
                );


                const dataTransfer = new DataTransfer();

                dataTransfer.items.add(processedFile);

                currentInput.files = dataTransfer.files;


                updatePreview(
                    currentInput,
                    URL.createObjectURL(processedFile)
                );


                closeCropper();

            },
            'image/jpeg',
            0.9
        );

    });


    cancelButton.addEventListener('click', function () {

        if (currentInput) {
            currentInput.value = '';
        }

        closeCropper();

    });


    function closeCropper() {

        if (cropper) {
            cropper.destroy();
            cropper = null;
        }

        cropImage.src = '';

        modal.classList.remove('show');

        currentInput = null;

    }


    function updatePreview(input, imageUrl) {

        const container = input.closest('.image-upload');

        let preview = container.querySelector(
            '.image-preview'
        );


        if (!preview) {

            preview = document.createElement('img');

            preview.className = 'image-preview';

            container.appendChild(preview);

        }


        preview.src = imageUrl;

    }

});