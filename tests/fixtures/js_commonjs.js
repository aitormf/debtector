/**
 * JavaScript fixture: CommonJS imports, arrow functions, class inheritance.
 * Tests patterns not covered by sample.ts (which is TypeScript-only).
 */

'use strict';

const path = require('path');
const fs = require('fs');

class Animal {
    speak() {
        return '...';
    }
}

class Dog extends Animal {
    speak() {
        return 'woof';
    }

    fetch() {
        return this.speak();
    }
}

const greet = (name) => {
    return `Hello, ${name}`;
};

function helper() {
    return greet('world');
}
