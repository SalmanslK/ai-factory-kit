**Corner Shop — Functional Specification, V1**

# 1 Introduction

This document specifies the online ordering system for a small corner shop.

## 1.1 Purpose

The shop wants its regular customers to order groceries online and collect them from the
counter, so that the queue at the till is shorter on busy Saturday mornings.

## 1.2 Users and roles

There are two roles. A Shopper browses prices, fills a cart and places orders. A Staff member
manages the price list and the discounts and sees every order. Both sign in with an email
address and a password; a Shopper may register themselves, a Staff member is added by the owner.

# 2 Modules

The modules below are listed in the order a Shopper meets them.

## 2.1 Pricing

Every product on the shelf has one current price. Prices are shown in pounds and pence,
including VAT, and a Shopper always sees the price that applies at the moment they look.

### 2.1.1 Price list

Staff keep the price list: a product name, a shelf code of up to 8 characters, and a price.
A shelf code is unique. A product with no price cannot be added to a cart.

### 2.1.2 Price changes

A Staff member may change a price at any time. A change takes effect immediately for new
carts; an item already in a cart keeps the price it was added at until checkout.

## 2.2 Discounts

Staff may create a discount as a percentage off one product or a fixed amount off an order.
A discount has a start and an end. Only one discount applies to an item, and when two could
apply "the larger saving wins". A discount never takes a price below zero.

## 2.3 Carts

A Shopper has one open cart. They add a product with a quantity between 1 and 20, change the
quantity, or remove it. The cart shows each line's price after any discount and the total. A
cart left untouched for 7 days is emptied.

## 2.4 Orders

Checking out a cart turns it into an order for collection.

### 2.4.1 Placing an order

A Shopper places an order by choosing a collection slot in the next 3 days. The order keeps
every line's price and discount as they were at checkout. A slot holds at most 10 orders; a
full slot cannot be chosen. The Shopper is shown "Your order is booked" with the slot.

### 2.4.2 Order history

A Shopper sees their own orders, newest first. Staff see every order and may mark one
collected or cancelled. A cancelled order cannot be collected, and a collected one cannot be
cancelled.

## 2.5 Loyalty

To be specified.

# 3 Glossary

Shelf code: the short code printed on the shelf label under a product. Collection slot: a
half-hour window in which an order may be collected at the counter.
