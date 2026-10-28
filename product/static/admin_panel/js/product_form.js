document.addEventListener('DOMContentLoaded', function () {

    let cropper = null;
    let currentInput = null;

    const modal = document.getElementById('crop-modal');
    const cropImage = document.getElementById('crop-image');
    const cropButton = document.getElementById('crop-button');
    const cancelButton = document.getElementById('crop-cancel');

    const temporaryImagesInput = document.getElementById(
        'temporary-images'
    );

    let temporaryImages = [];

    try {
        temporaryImages = JSON.parse(
            temporaryImagesInput?.value || '[]'
        );
    } catch (error) {
        temporaryImages = [];
    }

    const imageInputs = document.querySelectorAll(
        '.image-upload input[type="file"]'
    );


    function getFieldName(input) {

        return input.name;

    }


    function removeTemporaryReference(fieldName) {

        temporaryImages = temporaryImages.filter(
            item => item.field !== fieldName
        );

        updateTemporaryReferences();

    }


    function updateTemporaryReferences() {

        if (temporaryImagesInput) {

            temporaryImagesInput.value = JSON.stringify(
                temporaryImages
            );

        }

    }


    function updatePreview(input, imageUrl) {

        const container = input.closest('.image-upload');

        let preview = container.querySelector(
            '.image-preview'
        );

        if (!preview) {

            preview = document.createElement('img');

            preview.className = 'image-preview';

            preview.alt = 'Selected product image';

            container.appendChild(preview);

        }

        preview.src = imageUrl;

    }


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

                cropImage.onload = function () {

                    if (cropper) {
                        cropper.destroy();
                    }

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

                cropImage.src = event.target.result;

                modal.classList.add('show');

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

                if (!blob) {

                    alert('Unable to crop this image.');

                    return;

                }

                const originalFile = currentInput.files[0];

                const fileName =
                    originalFile.name.replace(/\.[^/.]+$/, '') +
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

                removeTemporaryReference(
                    getFieldName(currentInput)
                );

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


    updateTemporaryReferences();

        // Restore previews for images preserved by Django.
    const previewBaseUrl = temporaryImagesInput?.dataset.previewUrl;

    if (previewBaseUrl) {

        temporaryImages.forEach(function (item) {

            const input = document.querySelector(
                `.image-upload input[type="file"][name="${CSS.escape(item.field)}"]`
            );

            if (!input) {
                return;
            }

            const container = input.closest('.image-upload');

            if (!container) {
                return;
            }

            const previewContainer = container.querySelector(
                '.temporary-image-preview'
            );

            if (!previewContainer) {
                return;
            }

            const preview = document.createElement('img');

            preview.className = 'image-preview';

            preview.alt = 'Preserved cropped product image';

            const previewUrl = new URL(
                previewBaseUrl,
                window.location.origin
            );

            previewUrl.searchParams.set(
                'name',
                item.storage_name
            );

            preview.src = previewUrl.toString();

            previewContainer.replaceChildren(preview);

        });

    }

});