document.querySelectorAll(".password-toggle").forEach(button => {

    button.addEventListener("click", () => {

        const input = button.previousElementSibling;
        const icon = button.querySelector("i");

        if (input.type === "password") {

            input.type = "text";

            icon.classList.remove("fa-eye");
            icon.classList.add("fa-eye-slash");

            button.setAttribute("aria-label", "Hide password");

        } else {

            input.type = "password";

            icon.classList.remove("fa-eye-slash");
            icon.classList.add("fa-eye");

            button.setAttribute("aria-label", "Show password");
        }

    });

});