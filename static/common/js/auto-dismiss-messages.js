document.addEventListener("DOMContentLoaded", function () {

    "use strict";

    const messages = document.querySelectorAll(
        ".messages .message, .messages .qr-success-toast"
    );

    const DISMISS_DELAY = 5000;
    const ANIMATION_DELAY = 350;


    function dismissMessage(message) {

        if (!message || !message.isConnected) {
            return;
        }

        message.classList.add("message-exit");

        setTimeout(function () {
            message.remove();
        }, ANIMATION_DELAY);

    }


    messages.forEach(function (message) {

        const timer = setTimeout(function () {

            dismissMessage(message);

        }, DISMISS_DELAY);


        // Support optional manual close buttons.

        const closeButton = message.querySelector(
            ".message-close, .qr-toast-close"
        );

        if (closeButton) {

            closeButton.addEventListener("click", function () {

                clearTimeout(timer);

                dismissMessage(message);

            });

        }

    });

});