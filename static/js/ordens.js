"use strict";
const adicionar = document.getElementById("os-adicionar-peca");
if (adicionar) {
    adicionar.addEventListener("click", () => {
        const total = document.getElementById("id_pecas-TOTAL_FORMS");
        const modelo = document.getElementById("os-peca-vazia");
        window.GestatiFormsets.add(document.getElementById("os-pecas"), total, modelo);
    });
}
